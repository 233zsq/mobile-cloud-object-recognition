"""Create an experimental two-output release without changing its approved parent."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--experiment', type=Path, required=True)
parser.add_argument('--parent', type=Path, required=True)
parser.add_argument('--aux-data', type=Path, required=True)
parser.add_argument('--version', default='campus-evolve-v3')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
read = lambda path: json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8', newline='\n')


if args.output.exists():
    raise ValueError('Release version already exists; never overwrite a reviewed candidate')
report = read(args.experiment / 'report.json')
selection = read(args.experiment / 'selection.json')
parent = read(args.parent / 'metadata.json')
auxiliary = read(args.aux_data / 'metadata.json')
if (not report['development_targets_met'] or sha(args.experiment / 'model.tflite') != report['artifact']['model_sha256']
        or sha(args.experiment / 'selection.json') != report['selection_sha256']
        or sha(args.aux_data / 'samples.csv') != selection['auxiliary_manifest_sha256']):
    raise ValueError('Candidate failed its declared gates or source identities changed')
args.output.mkdir(parents=True)
shutil.copyfile(args.experiment / 'model.tflite', args.output / 'model.tflite')
shutil.copyfile(args.parent / 'labels.txt', args.output / 'labels.txt')
policy = {'policy_version': 'scope-knownness-v1', 'status': 'experimental', 'rule': 'learned_knownness_v1',
          'model_version': args.version, 'model_sha256': report['artifact']['model_sha256'],
          'labels_sha256': parent['labels_sha256'], 'category_version': parent['category_version'],
          'preprocessing_version': parent['input']['version'], 'confidence_threshold': .55, 'margin_threshold': .20,
          'knownness_threshold': selection['knownness_threshold'],
          'calibration': {'known_data_version': selection['known_data_version'],
                          'known_validation_sha256': selection['known_validation_sha256'],
                          'auxiliary_data_version': selection['auxiliary_data_version'],
                          'auxiliary_manifest_sha256': selection['auxiliary_manifest_sha256'],
                          'selection_sha256': report['selection_sha256']}}
write(args.output / 'scope-policy.json', policy)
(args.output / 'scope-policy.sha256').write_text(sha(args.output / 'scope-policy.json') + '\n', encoding='ascii', newline='\n')
metadata = {'status': 'experimental', 'requested_status': 'experimental', 'model_version': args.version,
            'created_at': datetime.now(timezone.utc).isoformat(), 'model_file': 'model.tflite',
            'sha256': report['artifact']['model_sha256'], 'model_bytes': report['artifact']['model_bytes'],
            'labels_file': 'labels.txt', 'labels_sha256': parent['labels_sha256'],
            'category_version': parent['category_version'], 'categories': parent['categories'],
            'data_version': selection['known_data_version'], 'scope_data_version': selection['auxiliary_data_version'],
            'experiment_id': args.experiment.name, 'parent_model_version': parent['model_version'],
            'parent_model_sha256': parent['sha256'], 'checkpoint_sha256': sha(args.experiment / 'candidate.keras'),
            'input': parent['input'], 'output': parent['output'],
            'score_output_index': report['artifact']['score_output_position'],
            'scope_output': {'index': report['artifact']['knownness_output_position'], 'shape': [1, 1], 'dtype': 'float32', 'interpretation': 'knownness'},
            'scope_policy_file': 'scope-policy.json', 'scope_policy_sha256': sha(args.output / 'scope-policy.json'),
            'low_confidence_threshold': parent['low_confidence_threshold'],
            'threshold_status': 'classification_threshold_inherited_from_unchanged_v2',
            'classification_weights_frozen': True, 'fp32_builtin_ops_only': True,
            'development_report_sha256': sha(args.experiment / 'report.json'),
            'independent_field_acceptance': 'pending', 'approval': 'pending_human',
            'known_issues': ['Known validation was used for policy selection.', 'Public unknown holdout is not a phone field test.',
                             'Unknown images can still pass. The original ten-class top-1 remains a candidate.']}
write(args.output / 'metadata.json', metadata)
write(args.output / 'open-set-development.json', report)
write(args.output / 'scope-data-metadata.json', auxiliary)
write(args.output / 'release-files.json', {path.name: sha(path) for path in sorted(args.output.iterdir()) if path.is_file()})
print(json.dumps({'model_version': args.version, 'status': metadata['status'], 'model_sha256': metadata['sha256'],
                  'policy_sha256': metadata['scope_policy_sha256'], 'model_bytes': metadata['model_bytes']}))
