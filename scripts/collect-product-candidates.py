"""Collect a small product-photo increment from observed Bing result URLs."""
import argparse
import json
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--sources', type=Path, required=True, help='UTF-8 TSV: image URL, product page URL')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--max-new', type=int, default=60)
args = parser.parse_args()
os.environ['RECOGNITION_ROOT'] = str(args.root.resolve())
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ml/src'))
from recognition.product import collect_products

result = collect_products(args.sources, args.output, max_new=args.max_new)
print(json.dumps({key: value for key, value in result.items() if key not in ('skipped', 'failures')}, ensure_ascii=False))
