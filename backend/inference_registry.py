"""Validated, operator-owned model allowlist shared by Flask and the CPU worker."""
import json
from pathlib import Path
import re

LABELS = ['cup', 'umbrella', 'book', 'pencil_case', 'mouse', 'keyboard', 'earphones', 'charger', 'key', 'backpack']


def load_registry(path):
    path = Path(path)
    if not path.is_absolute() or path.stat().st_size > 32768:
        raise ValueError('Expected a small absolute model registry')
    data = json.loads(path.read_text(encoding='utf-8'))
    entries = data.get('models')
    if data.get('schema_version') != 1 or not isinstance(entries, list) or not 1 <= len(entries) <= 4:
        raise ValueError('Registry supports one to four approved models')
    versions = set()
    for model in entries:
        if not isinstance(model, dict):
            raise ValueError('Invalid model entry')
        for key in ('model_version', 'category_version'):
            if not isinstance(model.get(key), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', model[key]):
                raise ValueError('Invalid model/category version')
        for key in ('model_sha256', 'labels_sha256'):
            if not isinstance(model.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', model[key]):
                raise ValueError('Invalid model/label hash')
        if model['model_version'] in versions or model.get('labels') != LABELS or model.get('status') != 'frozen':
            raise ValueError('Duplicate, incompatible or unapproved model')
        versions.add(model['model_version'])
        threshold = model.get('low_confidence_threshold')
        if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
            raise ValueError('Invalid threshold')
        for key, maximum in (('display_name', 64), ('description', 160)):
            if not isinstance(model.get(key), str) or not 1 <= len(model[key]) <= maximum:
                raise ValueError('Invalid display text')
        if not isinstance(model.get('package'), str) or not Path(model['package']).is_absolute():
            raise ValueError('Expected an absolute package path')
    if data.get('default_model_version') not in versions:
        raise ValueError('Default model is absent')
    return data


def public_contract(model):
    return {key: value for key, value in model.items() if key != 'package'}
