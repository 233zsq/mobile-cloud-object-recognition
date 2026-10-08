"""按实物分组划分训练/验证/测试集并冻结清单。

同一 object_id 的照片整体进入同一个集合，绝不跨集合分散；按类别内部独立划分，
使每类在三集合中都有代表。划分结果写入 data/splits/<data_version>/ 并计算清单哈希，
冻结后变更必须新建数据版本并记录原因。

运行目录：仓库根目录。
用法：
    python scripts/split_dataset.py data/manifests/sample-manifest.csv --data-version v1 --seed 42
依赖：仅 Python 3.10+ 标准库。
输出：data/splits/<data_version>/{train,validation,test}.csv 与 split-info.json。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from check_manifest import REQUIRED_COLUMNS, sha256_of

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RATIOS = {"train": 0.6, "validation": 0.2, "test": 0.2}
SPLIT_ORDER = ["train", "validation", "test"]


def assign_groups(object_ids: list[str], ratios: dict[str, float],
                  rng: random.Random) -> dict[str, str]:
    """把一组 object_id 按比例分配到各集合，返回 object_id -> split。"""
    objs = list(object_ids)
    rng.shuffle(objs)
    n = len(objs)
    assignment: dict[str, str] = {}
    if n < 3:
        # 实物少于3件：无法每集合一件，全部进训练集，由调用方告警
        return {o: "train" for o in objs}
    # 先保证验证、测试各至少1件
    assignment[objs[0]] = "test"
    assignment[objs[1]] = "validation"
    counts = {"train": 0, "validation": 1, "test": 1}
    for obj in objs[2:]:
        # 选当前占比距目标最欠的集合
        split = max(SPLIT_ORDER, key=lambda s: ratios[s] - counts[s] / n)
        assignment[obj] = split
        counts[split] += 1
    return assignment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="已审核的样本清单 CSV")
    parser.add_argument("--data-version", required=True,
                        help="数据版本号，如 v1；输出目录 data/splits/<版本>/")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认 42）")
    parser.add_argument("--include-pending", action="store_true",
                        help="默认只用 review_status=approved 的行；此选项同时纳入 pending")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = (root / args.manifest).resolve()
    out_dir = root / "data" / "splits" / args.data_version
    if out_dir.exists():
        print(f"错误：{out_dir} 已存在。冻结清单不可覆盖，请使用新数据版本。")
        return 1

    with manifest_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    usable = [r for r in rows
              if r.get("review_status") == "approved"
              or (args.include_pending and r.get("review_status") == "pending")]
    skipped = len(rows) - len(usable)
    if skipped:
        print(f"跳过 {skipped} 行（review_status 非 approved）")

    # 按类别收集实物
    cat_objects: dict[str, set[str]] = defaultdict(set)
    for r in usable:
        cat_objects[r["category_id"]].add(r["object_id"])

    rng = random.Random(args.seed)
    obj_split: dict[tuple[str, str], str] = {}
    warnings: list[str] = []
    for cid in sorted(cat_objects):
        objs = sorted(cat_objects[cid])
        if len(objs) < 3:
            warnings.append(
                f"类别 {cid} 只有 {len(objs)} 件实物，无法按实物分到三个集合，"
                "已全部划入训练集；验证/测试对该类无实物泛化意义，建议补采。"
            )
        for obj, split in assign_groups(objs, RATIOS, rng).items():
            obj_split[(cid, obj)] = split

    split_rows: dict[str, list[dict]] = {s: [] for s in SPLIT_ORDER}
    for r in usable:
        split = obj_split[(r["category_id"], r["object_id"])]
        row = dict(r)
        row["split_name"] = split
        row["data_version"] = args.data_version
        split_rows[split].append(row)

    out_dir.mkdir(parents=True)
    info: dict = {
        "data_version": args.data_version,
        "seed": args.seed,
        "ratios": RATIOS,
        "source_manifest": args.manifest,
        "source_manifest_sha256": sha256_of(manifest_path),
        "rule": "同一 object_id 整体划入一个集合；类别内独立划分；实物不足3件的类别全部入训练集",
        "counts": {},
        "files": {},
        "warnings": warnings,
    }
    for split in SPLIT_ORDER:
        path = out_dir / f"{split}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerows(split_rows[split])
        info["files"][split] = {
            "path": str(path.relative_to(root)),
            "rows": len(split_rows[split]),
            "sha256": sha256_of(path),
        }
        per_cat: dict[str, int] = defaultdict(int)
        for r in split_rows[split]:
            per_cat[r["category_id"]] += 1
        info["counts"][split] = dict(sorted(per_cat.items()))

    with (out_dir / "split-info.json").open("w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"划分完成 -> {out_dir}")
    for split in SPLIT_ORDER:
        print(f"  {split}: {len(split_rows[split])} 张  {info['counts'][split]}")
    for w in warnings:
        print(f"  [警告] {w}")
    test_count = len(split_rows["test"])
    if test_count < 180:
        print(f"  [警告] 测试集 {test_count} 张，低于计划约 200 张的独立评估规模。")
    print("测试清单已冻结，组长保管；训练、选参、阈值选择与量化校准不得使用 test.csv。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
