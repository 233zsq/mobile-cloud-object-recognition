"""样本清单检查：字段校验、文件存在与可解码、SHA-256 核对与补算、重复与模糊检测。

运行目录：仓库根目录。
用法：
    python scripts/check_manifest.py data/manifests/sample-manifest.csv
    python scripts/check_manifest.py data/manifests/sample-manifest.csv --check-files --fill-sha256
依赖：Python 3.10+；--check-files 需要 Pillow 和 numpy（训练环境中已有）。
输出：终端报告；问题行打印到 stdout，退出码 0=无错误 1=存在错误。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REQUIRED_COLUMNS = [
    "sample_id", "image_path", "image_sha256", "category_id", "object_id",
    "session_id", "collector", "captured_at", "split_name", "review_status",
    "data_version",
]
VALID_CATEGORY_IDS = {str(i) for i in range(10)}
VALID_SPLITS = {"", "train", "validation", "test"}
VALID_REVIEW = {"pending", "approved", "rejected"}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sharpness(path: Path) -> float:
    """灰度图拉普拉斯方差，越低越模糊。阈值仅为启发式，需按实际分布调整。"""
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        gray = np.asarray(im.convert("L").resize((224, 224)), dtype=np.float64)
    lap = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1] + gray[2:, 1:-1]
        + gray[1:-1, :-2] + gray[1:-1, 2:]
    )
    return float(lap.var())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="样本清单 CSV，路径相对仓库根目录")
    parser.add_argument("--check-files", action="store_true",
                        help="读取图片文件：核对/补算哈希、解码检查、模糊检测")
    parser.add_argument("--fill-sha256", action="store_true",
                        help="对 image_sha256 为空的行回填实际哈希（改写清单文件）")
    parser.add_argument("--blur-threshold", type=float, default=50.0,
                        help="拉普拉斯方差低于此值标记为疑似模糊（默认 50.0）")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = (root / args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"错误：清单不存在 {manifest_path}")
        return 1

    with manifest_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        rows = list(reader)

    errors: list[str] = []
    warnings: list[str] = []

    if columns != REQUIRED_COLUMNS:
        errors.append(f"表头与模板不一致：{columns}，应为 {REQUIRED_COLUMNS}")

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
                errors.append(f"{where} 哈希不匹配：记录 {recorded[:12]}… 实际 {actual[:12]}…")
            elif not recorded:
                if args.fill_sha256:
                    row["image_sha256"] = actual
                    changed = True
                else:
                    warnings.append(f"{where} image_sha256 为空（--fill-sha256 可回填）")
            hash_to_ids[actual].append(sid)
            try:
                s = sharpness(img)
                if s < args.blur_threshold:
                    warnings.append(f"{where} 疑似模糊：清晰度 {s:.1f} < {args.blur_threshold}")
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

    if changed:
        with manifest_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n已回填 SHA-256 并写回 {manifest_path}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
