"""Readonly validation probe. Use the independent LiteRT CPU environment."""
import argparse
import json
from pathlib import Path
from recognition.scope import probe

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--release', required=True, type=Path)
parser.add_argument('--data-version', required=True)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
report = probe(args.release, args.data_version, args.output)
print(json.dumps({'selected': report['selected'], 'policy_sha256': report['policy_sha256'],
                  'unknown_rejection_rate': None}, ensure_ascii=False))
