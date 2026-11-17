"""Rebuildable, content-addressed parser cache. Hashes are always rechecked."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from .storage import cache_dir, sha256_file, write_json_atomic
from .security import secret_matches

PARSER_VERSION = 1

class AnalysisCache:
    def __init__(self, root: Path, *, full: bool = False, namespace: str = "analysis"):
        self.path = cache_dir(root) / (namespace + '.json')
        self.full = full
        self.entries = {}
        self.processed = self.reused = 0
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if raw.get('schema_version') == 1 and raw.get('parser_version') == PARSER_VERSION and isinstance(raw.get('entries'),dict):
                self.entries = raw['entries']
        except (OSError, ValueError, AttributeError): pass
        self.next = {}
    def get(self, name: str, fingerprint: str, parse):
        item = self.entries.get(name)
        if not self.full and isinstance(item,dict) and item.get('input') == fingerprint and item.get('digest') == digest(item.get('value')):
            self.reused += 1; result = item['value']
        else:
            self.processed += 1; result = parse()
        if not secret_matches(json.dumps(result,ensure_ascii=False)):
            self.next[name] = {'input':fingerprint,'digest':digest(result),'value':result}
        return result
    def save(self):
        write_json_atomic(self.path, {'schema_version':1,'parser_version':PARSER_VERSION,'entries':self.next})
    def stats(self):return {'processed':self.processed,'reused':self.reused,'full':self.full,'hash_verification':'all discovered files; never mtime only'}

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def config_digest(root: Path):
    return digest({name: sha256_file(root/name) if (root/name).is_file() else None for name in ('.gitignore','.pctxignore','.project-context/manifest.json')})
