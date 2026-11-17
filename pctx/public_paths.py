"""Literal public project paths, including safe coordination directories."""
from pathlib import Path,PurePosixPath
import re

DENIED={'.git','.project-context','.private','.ssh','.gnupg','.aws','.azure','.kube','.config','.cache','.venv','node_modules'}

def syntax(value):
    if not isinstance(value,str) or not value or len(value)>500 or value!=value.strip() or any(ord(c)<32 for c in value) or '\\' in value or ':' in value or any(c in value for c in '*?[]'):
        raise ValueError('Use a literal public project-relative path')
    parts=value.split('/')
    if PurePosixPath(value).is_absolute() or any(p in {'','.', '..'} or p.casefold() in DENIED or p.startswith('.env') for p in parts):
        raise ValueError('Private or escaping project path unavailable')
    if any(re.search(r'(?i)(secret|credential|password|auth\.json)',p) for p in parts) or PurePosixPath(value).suffix.casefold() in {'.key','.pem','.p12','.pfx'}:
        raise ValueError('Private project path unavailable')
    return value


def resolve(root,value):
    from .storage import safe_relative
    syntax(value);cursor=root
    for part in value.split('/'):
        cursor=cursor/part
        if cursor.is_symlink() or (cursor.is_file() and cursor.stat().st_nlink>1):
            raise ValueError('Symlink or hard-linked project path unavailable')
    return safe_relative(root,value)
