"""Optional offline ONNX sentence encoder. No download or provider fallback."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def similarity(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b) or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in [*a, *b]):
        raise ValueError('Invalid vector dimensions or nonfinite values; rebuild index')
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    if not norm or not math.isfinite(norm):
        raise ValueError('Zero vector; rebuild index')
    return sum(x*y for x, y in zip(a, b, strict=True)) / norm


class LocalEncoder:
    """Explicit bundle: tokenizer.json, model.onnx and pctx-embedding.json.

    Supported contract: HuggingFace tokenizer JSON, int64 token inputs and
    float token embeddings, attention-mask mean pooling. No custom Python code.
    """
    def __init__(self, directory: Path):
        directory = directory.resolve()
        try:
            configuration = directory / 'pctx-embedding.json'
            if configuration.is_symlink() or configuration.stat().st_size > 8192:
                raise ValueError('Invalid model configuration path or size')
            config = json.loads(configuration.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('Local embedding bundle unavailable; specify an existing model directory') from exc
        if not isinstance(config, dict) or config.get('schema') != 1 or config.get('pooling') != 'attention-mean':
            raise ValueError('Unsupported local embedding contract')
        self.length = config.get('max_length', 128)
        if not isinstance(self.length, int) or not 16 <= self.length <= 512:
            raise ValueError('Embedding max_length must be 16..512')
        paths = []
        for key in ('model', 'tokenizer'):
            name = config.get(key)
            if not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Model files must be local relative paths')
            path = directory / name
            if not path.is_file() or path.is_symlink() or directory not in path.resolve().parents or any(
                    parent.is_symlink() for parent in path.parents if directory in parent.parents):
                raise ValueError('Local embedding file unavailable')
            paths.append(path)
        digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
        for path in paths:
            with path.open('rb') as handle:
                for block in iter(lambda: handle.read(1024*1024), b''):
                    digest.update(block)
        self.fingerprint = digest.hexdigest()
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError('Local embeddings require optional packages: install pctx[semantic] in your environment') from exc
        self.np = np
        self.truncated_inputs = 0
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        try:
            self.tokenizer = Tokenizer.from_file(str(paths[1]))
            self.tokenizer.enable_truncation(max_length=self.length)
            self.tokenizer.enable_padding(length=self.length, pad_id=int(config.get('pad_id', 0)),
                                          pad_token=str(config.get('pad_token', '[PAD]')))
            self.session = ort.InferenceSession(str(paths[0]), sess_options=options, providers=['CPUExecutionProvider'])
        except Exception as exc:
            raise ValueError('Invalid local ONNX/tokenizer bundle: ' + type(exc).__name__) from exc
        self.inputs = [item.name for item in self.session.get_inputs()]
        if not set(self.inputs) <= {'input_ids', 'attention_mask', 'token_type_ids'}:
            raise ValueError('Unsupported ONNX inputs')
        self.output = config.get('output', 'last_hidden_state')
        if self.output not in {x.name for x in self.session.get_outputs()}:
            raise ValueError('Unsupported ONNX token output')

    def encode(self, texts: list[str]) -> list[list[float]]:
        np, result = self.np, []
        for start in range(0, len(texts), 16):
            batch = self.tokenizer.encode_batch(texts[start:start + 16])
            self.truncated_inputs += sum(bool(x.overflowing) for x in batch)
            feeds = {'input_ids': np.asarray([x.ids for x in batch], dtype=np.int64),
                     'attention_mask': np.asarray([x.attention_mask for x in batch], dtype=np.int64),
                     'token_type_ids': np.asarray([x.type_ids for x in batch], dtype=np.int64)}
            try:
                vectors = self.session.run([self.output], {key: feeds[key] for key in self.inputs})[0]
            except Exception as exc:
                raise ValueError('Local model inference failed: ' + type(exc).__name__) from exc
            if vectors.ndim != 3 or vectors.shape[:2] != feeds['input_ids'].shape:
                raise ValueError('ONNX model must return token embeddings')
            mask = feeds['attention_mask'][:, :, None]
            pooled = (vectors * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            if not np.isfinite(pooled).all() or (norms == 0).any():
                raise ValueError('Encoder produced invalid vectors')
            result.extend((pooled / norms).tolist())
        return result
