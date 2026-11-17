"""Shared, conservative checks used before context leaves the local store."""

from __future__ import annotations

import re


SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghs|ghr|ghu)_[A-Za-z0-9_]{20,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic-secret-assignment", re.compile(r"(?i)\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9/+=_-]{16,}")),
]

INJECTION_PATTERN = re.compile(r"(?i)(ignore\s+(all\s+)?previous\s+instructions|reveal\s+(the\s+)?secret|system\s+message|disable\s+safety)")


def secret_matches(text: str) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS if pattern.search(text)]


def looks_like_instruction_override(text: str) -> bool:
    return bool(INJECTION_PATTERN.search(text))
