#!/usr/bin/env python
"""正式模型包接收校验（docs/model-contract.md 的接收方检查）。

用法（仓库根目录）：
    python scripts/verify-official-model.py [模型包目录]

默认检查 android/app/src/main/assets/models/。校验内容：
1. metadata.json / labels.txt / model.tflite 三件套齐备；
2. model.tflite 的 SHA-256 与 metadata.sha256 一致；
3. labels.txt 的 SHA-256 与 metadata.labels_sha256 一致；
4. 标签行数 = 10，且顺序与 shared/categories.json（冻结版）的 label_key 一致；
5. 打印 input 契约摘要（版本/形状/归一化/阈值），供与 docs/model-contract.md 比对。

任一失败返回非零退出码；全部通过打印 "OK"。
"""

import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(REPO_ROOT, "android", "app", "src", "main", "assets", "models")
CATEGORIES_PATH = os.path.join(REPO_ROOT, "shared", "categories.json")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    model_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    errors = []

    metadata_path = os.path.join(model_dir, "metadata.json")
    if not os.path.isfile(metadata_path):
        print(f"缺少 metadata.json：{metadata_path}")
        sys.exit(1)
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    model_path = os.path.join(model_dir, metadata.get("model_file", "model.tflite"))
    labels_path = os.path.join(model_dir, metadata.get("labels_file", "labels.txt"))
    for path, name in ((model_path, "模型文件"), (labels_path, "标签文件")):
        if not os.path.isfile(path):
            errors.append(f"缺少{name}：{path}")

    version = metadata.get("model_version")
    print(f"model_version : {version}")
    print(f"status        : {metadata.get('status')}")
    print(f"category_ver  : {metadata.get('category_version')}")
    input_spec = metadata.get("input", {})
    print(f"input         : version={input_spec.get('version')} shape={input_spec.get('shape')} "
          f"dtype={input_spec.get('dtype')} range={input_spec.get('pixel_range')}")
    print(f"normalization : {input_spec.get('normalization')}")
    print(f"threshold     : {metadata.get('low_confidence_threshold')} "
          f"({metadata.get('threshold_status')})")

    if not errors:
        model_sha = sha256_file(model_path)
        labels_sha = sha256_file(labels_path)
        print(f"model sha256  : {model_sha}")
        print(f"labels sha256 : {labels_sha}")
        expected_model = metadata.get("sha256")
        expected_labels = metadata.get("labels_sha256")
        if expected_model and model_sha != expected_model:
            errors.append(f"model.tflite SHA-256 不一致：期望 {expected_model}")
        if expected_labels and labels_sha != expected_labels:
            errors.append(f"labels.txt SHA-256 不一致：期望 {expected_labels}")

        with open(labels_path, "r", encoding="utf-8") as f:
            labels = [line.strip() for line in f if line.strip()]
        with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
            categories = json.load(f)
        expected_keys = [c["label_key"] for c in categories["categories"]]
        print(f"labels        : {len(labels)} 行")
        if labels != expected_keys:
            errors.append(
                "labels.txt 顺序与 shared/categories.json 不一致\n"
                f"  标签文件: {labels}\n  冻结清单: {expected_keys}"
            )

    if errors:
        print("\n[FAIL] 校验未通过：")
        for e in errors:
            print(" -", e)
        sys.exit(1)

    print("\nOK：模型包与元数据、冻结类别清单一致，可复制到 assets/models/ 构建。")


if __name__ == "__main__":
    main()