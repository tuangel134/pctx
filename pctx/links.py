"""Portable explicit knowledge relations; no database dependency."""
from pathlib import Path

RELATIONS = {'affects', 'contradicts', 'replaces', 'supports', 'depends_on'}

def validate_links(links: object) -> list[dict]:
    if not isinstance(links, list) or len(links) > 100:
        raise ValueError('links must be an array of at most 100 relations')
    result = []
    for link in links:
        if not isinstance(link, dict) or link.get('relation') not in RELATIONS:
            raise ValueError('Invalid knowledge relation')
        target = link.get('target')
        if not isinstance(target, str) or len(target) > 500 or not target.startswith(('record:', 'file:')):
            raise ValueError('Link target must be record:ID or file:relative/path')
        value = target.split(':', 1)[1]
        if not value or any(c in value for c in '\n\r\0'):
            raise ValueError('Invalid knowledge target')
        if target.startswith('file:') and (Path(value).is_absolute() or '..' in Path(value).parts or '\\' in value):
            raise ValueError('Link file paths must stay inside the project')
        result.append({'relation': link['relation'], 'target': target})
    return sorted(result, key=lambda x: (x['relation'], x['target']))

