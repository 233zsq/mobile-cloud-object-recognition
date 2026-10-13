"""Collect a small product-photo increment from observed Bing result URLs."""

import argparse
import json
import os
from pathlib import Path


def run(args):
    os.environ["RECOGNITION_ROOT"] = str(args.root.resolve())
    from recognition.product import collect_products

    result = collect_products(args.sources, args.output, max_new=args.max_new)
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in ("skipped", "failures")
            },
            ensure_ascii=False,
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--sources",
        type=Path,
        required=True,
        help="UTF-8 TSV: image URL, product page URL",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-new", type=int, default=60)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
