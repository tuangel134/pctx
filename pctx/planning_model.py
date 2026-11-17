"""Portable checklist extension; no provider or database dependency."""
import re

KINDS = ('goal', 'task', 'bug', 'check')
STATUSES = ('pending', 'in_progress', 'done', 'needs_review', 'blocked', 'verified', 'cancelled')
DIFFICULTIES = ('unknown', 'easy', 'medium', 'intermediate', 'hard', 'very_hard')
RISKS = ('unknown', 'low', 'medium', 'high')
PRIORITIES = ('low', 'normal', 'high', 'critical')
OUTCOMES = ('passed', 'failed', 'blocked', 'inconclusive')
LABELS = dict(zip(DIFFICULTIES, ('Sin clasificar', 'Fácil', 'Medio', 'Intermedio', 'Difícil', 'Súper difícil')))

def validate_checklist(value):
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('Unsupported checklist schema')
    for field, options in [('kind', KINDS), ('status', STATUSES), ('difficulty', DIFFICULTIES), ('risk', RISKS), ('priority', PRIORITIES)]:
        if value.get(field) not in options:
            raise ValueError('Invalid checklist ' + field)
    for field, limit in [('title', 300), ('description', 4000), ('owner', 160), ('reason', 1000), ('difficulty_reason', 1000)]:
        text = value.get(field)
        if not isinstance(text, str) or len(text) > limit or (field == 'title' and not text.strip()):
            raise ValueError('Invalid checklist ' + field)
    if value['difficulty'] != 'unknown' and not value['difficulty_reason'].strip():
        raise ValueError('Classified work requires a difficulty reason')
    parent = value.get('parent')
    if parent is not None and (not isinstance(parent, str) or not re.fullmatch(r'plan\.[A-Za-z0-9_-]{1,100}', parent)):
        raise ValueError('Invalid checklist parent')
    deps = value.get('dependencies')
    if not isinstance(deps, list) or len(deps) > 50 or any(not isinstance(x, str) or not re.fullmatch(r'plan\.[A-Za-z0-9_-]{1,100}', x) for x in deps) or len(set(deps)) != len(deps):
        raise ValueError('Invalid checklist dependencies')
    criteria = value.get('criteria')
    if not isinstance(criteria, list) or len(criteria) > 50:
        raise ValueError('Invalid acceptance criteria')
    ids = set()
    for c in criteria:
        if not isinstance(c, dict) or not isinstance(c.get('id'), str) or not isinstance(c.get('text'), str) or not 1 <= len(c['text'].strip()) <= 500 or c['id'] in ids:
            raise ValueError('Invalid acceptance criterion')
        ids.add(c['id'])
    generation = value.get('work_generation', 0)
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError('Invalid checklist work generation')
    count = value.get('review_count')
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError('Invalid review count')
    review = value.get('last_review')
    if (count == 0) != (review is None):
        raise ValueError('Review count must match the recorded review')
    if review is not None:
        if not isinstance(review, dict) or review.get('outcome') not in OUTCOMES or not isinstance(review.get('id'), str) or not isinstance(review.get('summary'), str) or not isinstance(review.get('criteria'), list) or not isinstance(review.get('evidence'), list):
            raise ValueError('Invalid recorded review')
        for field, maximum in [('id', 100), ('summary', 2000), ('reviewer', 160), ('at', 40)]:
            if not isinstance(review.get(field), str) or not 1 <= len(review[field].strip()) <= maximum:
                raise ValueError('Invalid review ' + field)
        for field in ['definition_hash', 'request_hash']:
            if not isinstance(review.get(field), str) or not re.fullmatch('[a-f0-9]{64}', review[field]):
                raise ValueError('Invalid review hash')
        if len(review['criteria']) > 50 or any(not isinstance(x, str) for x in review['criteria']) or len(set(review['criteria'])) != len(review['criteria']):
            raise ValueError('Invalid review criteria')
        if len(review['evidence']) > 30:
            raise ValueError('Invalid review evidence')
        for e in review['evidence']:
            if isinstance(e,dict) and e.get('kind')=='git':
                if not isinstance(e.get('branch'),str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,300}',e['branch']) or not isinstance(e.get('commit'),str) or not re.fullmatch('[a-fA-F0-9]{40,64}',e['commit']):
                    raise ValueError('Invalid Git review evidence')
                continue
            if not isinstance(e, dict) or not isinstance(e.get('path'), str) or not 1 <= len(e['path']) <= 500 or not isinstance(e.get('content_hash'), str) or not re.fullmatch('[a-f0-9]{64}', e['content_hash']):
                raise ValueError('Invalid review evidence')
        related = review.get('related_revisions')
        if not isinstance(related, dict) or any(not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int) or v < 1 for k, v in related.items()):
            raise ValueError('Invalid related review revisions')
    return value


def audit_checklist_history(record, revisions):
    seen = {}
    for revision in revisions:
        item = validate_checklist(revision['record'].get('checklist'))
        review = item['last_review']
        if review:
            if review['id'] in seen and seen[review['id']] != review:
                raise ValueError('Checklist review event was altered')
            seen[review['id']] = review
        if item['review_count'] != len(seen):
            raise ValueError('Checklist review count differs from recorded history')
    if record['checklist']['review_count'] != len(seen):
        raise ValueError('Checklist review count requires intact history')
