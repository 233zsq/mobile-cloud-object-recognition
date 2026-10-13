"""Legacy 11-column collection checks and 60/20/20 object-group splitting.

Formal training and review imports remain in recognition.data and recognition.evolution.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from recognition.manifest_io import (
    LEGACY_FIELDS,
    atomic_write,
    digest as sha256_of,
    read_legacy_manifest as read_manifest,
    write_legacy_manifest as write_manifest_atomic,
)

REQUIRED_COLUMNS = LEGACY_FIELDS
VALID_CATEGORY_IDS = {str(i) for i in range(10)}
VALID_SPLITS = {"", "train", "validation", "test"}
VALID_REVIEW = {"pending", "approved", "rejected"}
RATIOS = {"train": 0.6, "validation": 0.2, "test": 0.2}
SPLIT_ORDER = ["train", "validation", "test"]


def sharpness(path: Path) -> float:
    """灰度图拉普拉斯方差，越低越模糊。阈值仅为启发式，需按实际分布调整。"""
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        gray = np.asarray(im.convert("L").resize((224, 224)), dtype=np.float64)
    lap = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    return float(lap.var())


def check_main(root: Path, *, sharpness=sharpness) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="样本清单 CSV，路径相对仓库根目录")
    parser.add_argument(
        "--check-files",
        action="store_true",
        help="读取图片文件：核对/补算哈希、解码检查、模糊检测",
    )
    parser.add_argument(
        "--fill-sha256",
        action="store_true",
        help="对 image_sha256 为空的行回填实际哈希（改写清单文件）",
    )
    parser.add_argument(
        "--blur-threshold",
        type=float,
        default=50.0,
        help="拉普拉斯方差低于此值标记为疑似模糊（默认 50.0）",
    )
    args = parser.parse_args()

    manifest_path = (root / args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"错误：清单不存在 {manifest_path}")
        return 1

    try:
        rows = read_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}")
        return 1

    errors: list[str] = []
    warnings: list[str] = []

    seen_ids: set[str] = set()
    hash_to_ids: dict[str, list[str]] = defaultdict(list)
    cat_counts: Counter[str] = Counter()
    collector_counts: Counter[str] = Counter()
    cat_objects: dict[str, set[str]] = defaultdict(set)
    changed = False

    for i, row in enumerate(rows, start=2):
        sid = row.get("sample_id", "").strip()
        where = f"第{i}行({sid or '无sample_id'})"
        if not sid:
            errors.append(f"{where} sample_id 为空")
        elif sid in seen_ids:
            errors.append(f"{where} sample_id 重复")
        seen_ids.add(sid)

        if row.get("category_id", "").strip() not in VALID_CATEGORY_IDS:
            errors.append(f"{where} category_id 非法：{row.get('category_id')!r}")
        if row.get("split_name", "").strip() not in VALID_SPLITS:
            errors.append(f"{where} split_name 非法：{row.get('split_name')!r}")
        if row.get("review_status", "").strip() not in VALID_REVIEW:
            errors.append(f"{where} review_status 非法：{row.get('review_status')!r}")
        for col in ("image_path", "object_id", "session_id", "collector"):
            if not row.get(col, "").strip():
                errors.append(f"{where} {col} 为空")

        cat_counts[row.get("category_id", "?")] += 1
        collector_counts[row.get("collector", "?")] += 1
        cat_objects[row.get("category_id", "?")].add(row.get("object_id", ""))

        if args.check_files and row.get("image_path", "").strip():
            img = (root / row["image_path"].strip()).resolve()
            if not img.is_file():
                errors.append(f"{where} 文件不存在：{row['image_path']}")
                continue
            actual = sha256_of(img)
            recorded = row.get("image_sha256", "").strip()
            if recorded and recorded != actual:
                errors.append(
                    f"{where} 哈希不匹配：记录 {recorded[:12]}… 实际 {actual[:12]}…"
                )
            elif not recorded:
                if args.fill_sha256:
                    row["image_sha256"] = actual
                    changed = True
                else:
                    warnings.append(
                        f"{where} image_sha256 为空（--fill-sha256 可回填）"
                    )
            hash_to_ids[actual].append(sid)
            try:
                s = sharpness(img)
                if s < args.blur_threshold:
                    warnings.append(
                        f"{where} 疑似模糊：清晰度 {s:.1f} < {args.blur_threshold}"
                    )
            except Exception as exc:
                errors.append(f"{where} 无法解码为图片：{exc}")

    for digest, ids in hash_to_ids.items():
        if len(ids) > 1:
            errors.append(f"重复图片（哈希 {digest[:12]}…）：{', '.join(ids)}")

    print("=== 类别统计 ===")
    for cid in sorted(cat_counts):
        n_obj = len(cat_objects[cid] - {""})
        flag = "" if n_obj >= 5 else "  ⚠ 实物不足5件"
        print(f"  类别 {cid}: {cat_counts[cid]} 张, {n_obj} 件实物{flag}")
    print("=== 采集者统计 ===")
    for person, n in sorted(collector_counts.items()):
        print(f"  {person}: {n} 张")
    print(f"合计 {len(rows)} 行")

    print(f"\n=== 警告 {len(warnings)} 条 ===")
    for w in warnings:
        print(f"  [警告] {w}")
    print(f"\n=== 错误 {len(errors)} 条 ===")
    for e in errors:
        print(f"  [错误] {e}")

    if changed and not errors:
        try:
            write_manifest_atomic(manifest_path, rows)
        except (OSError, ValueError) as exc:
            print(f"错误：回填失败，原清单未替换：{exc}")
            return 1
        print(f"\n已回填 SHA-256 并写回 {manifest_path}")
    elif changed:
        print("\n存在错误，未回填 SHA-256，原清单保持不变。")

    return 1 if errors else 0


def assign_groups(
    object_ids: list[str], ratios: dict[str, float], rng: random.Random
) -> dict[str, str]:
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


def split_main(root: Path) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="已审核的样本清单 CSV")
    parser.add_argument(
        "--data-version",
        required=True,
        help="数据版本号，如 v1；输出目录 data/splits/<版本>/",
    )
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认 42）")
    parser.add_argument(
        "--include-pending",
        action="store_true",
        help="默认只用 review_status=approved 的行；此选项同时纳入 pending",
    )
    args = parser.parse_args()

    manifest_path = (root / args.manifest).resolve()
    out_dir = root / "data" / "splits" / args.data_version
    if out_dir.exists():
        print(f"错误：{out_dir} 已存在。冻结清单不可覆盖，请使用新数据版本。")
        return 1

    try:
        rows = read_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}")
        return 1

    usable = [
        r
        for r in rows
        if r.get("review_status") == "approved"
        or (args.include_pending and r.get("review_status") == "pending")
    ]
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
        write_manifest_atomic(path, split_rows[split])
        info["files"][split] = {
            "path": str(path.relative_to(root)),
            "rows": len(split_rows[split]),
            "sha256": sha256_of(path),
        }
        per_cat: dict[str, int] = defaultdict(int)
        for r in split_rows[split]:
            per_cat[r["category_id"]] += 1
        info["counts"][split] = dict(sorted(per_cat.items()))

    atomic_write(
        out_dir / "split-info.json",
        lambda stream: json.dump(info, stream, ensure_ascii=False, indent=2),
    )

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
