"""Check, distribute or export versioned categories, labels and scope policies."""

import argparse
import json
from pathlib import Path
import sys
from .distribution import Catalog, GROUPS, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root containing shared/config-distribution.json",
    )
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("check", "generate"):
        command = actions.add_parser(action)
        command.add_argument(
            "--target",
            action="append",
            choices=GROUPS,
            help="Select groups; defaults to every group",
        )
    command = actions.add_parser("export")
    command.add_argument("--category-version", required=True)
    command.add_argument("--model-version")
    command.add_argument("--policy-version")
    command.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New output directory; existing directories are never overwritten",
    )
    args = parser.parse_args()
    try:
        catalog = Catalog(args.root)
        if args.action == "export":
            result = catalog.export(
                args.output,
                args.category_version,
                args.model_version,
                args.policy_version,
            )
        elif args.action == "generate":
            result = {
                "changed": catalog.generate(tuple(dict.fromkeys(args.target or GROUPS)))
            }
        else:
            differences = catalog.check(tuple(dict.fromkeys(args.target or GROUPS)))
            result = {"ok": not differences, "differences": differences}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.action == "check" and differences else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
