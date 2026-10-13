"""Verify deployment bytes and approval without importing a training runtime."""
import hashlib
import json
from pathlib import Path


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            result.update(block)
    return result.hexdigest()


def verify_package(root=Path(__file__).resolve().parent):
    root = Path(root).resolve(strict=True)
    inventory = json.loads((root / 'checksums.json').read_text(encoding='utf-8'))
    for relative, expected in inventory['files'].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256(path) != expected:
            raise ValueError('Deployment file missing or hash mismatch: ' + relative)
    release = root / 'release'
    meta = json.loads((release / 'metadata.json').read_text(encoding='utf-8'))
    if meta['status'] != 'frozen' or meta['model_version'] != inventory['model_version']:
        raise ValueError('A matching frozen model is required')
    if sha256(release / 'model.tflite') != meta['sha256'] or sha256(release / 'labels.txt') != meta['labels_sha256']:
        raise ValueError('Model or label identity mismatch')
    if (release / 'model.tflite').stat().st_size != meta['model_bytes'] or meta['model_bytes'] > 15_000_000:
        raise ValueError('Actual model size violates the contract')
    labels = (release / 'labels.txt').read_text(encoding='utf-8').splitlines()
    if len(labels) != 10 or labels != [c['label_key'] for c in meta['categories']]:
        raise ValueError('Category order differs from model labels')
    if meta.get('scope_output') is not None:
        policy_path = release / 'scope-policy.json'
        if sha256(policy_path) != meta.get('scope_policy_sha256'):
            raise ValueError('Scope policy hash differs')
        policy = json.loads(policy_path.read_text(encoding='utf8'))
        if (policy.get('model_sha256'), policy.get('model_version'), policy.get('labels_sha256')) != (
                meta['sha256'], meta['model_version'], meta['labels_sha256']):
            raise ValueError('Scope policy belongs to another model')
        approval = json.loads((release / 'approval.json').read_text(encoding='utf8'))
        comparison = release / 'independent-runtime.json'
        if (meta.get('approval') != 'approved' or approval.get('status') != 'approved'
                or approval.get('model_sha256') != meta['sha256']
                or approval.get('policy_sha256') != meta['scope_policy_sha256']
                or approval.get('comparison_sha256') != sha256(comparison)):
            raise ValueError('Human approval must bind model, policy and comparison')
    if meta.get('deployment_approval') == 'pending_human_approval':
        approval = json.loads((release / 'approval.json').read_text(encoding='utf-8'))
        report = root / 'comparison.json'
        if (approval.get('status') != 'approved' or approval.get('model_version') != meta['model_version']
                or approval.get('model_sha256') != meta['sha256'] or approval.get('report_sha256') != sha256(report)
                or json.loads(report.read_text(encoding='utf-8'))['candidate']['sha256'] != meta['sha256']):
            raise ValueError('Matching human approval and comparison report are required')
    return {'passed': True, 'checked_files': len(inventory['files']),
            'model_version': meta['model_version'], 'model_sha256': meta['sha256']}


if __name__ == '__main__':
    print(json.dumps(verify_package(), ensure_ascii=False))
