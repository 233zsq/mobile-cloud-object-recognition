#!/usr/bin/env python
"""生成占位验证模型（10 类随机权重 MobileNetV2 tflite）。

用途：在训练负责人交付正式模型之前，验证 Android 端「加载-校验-预处理-推理-显示」链路
（10月8日检查点）。随机权重输出接近均匀分布，恰好用于联调低置信提示与人工纠错流程。

注意：该模型不能用于任何准确率结论；正式模型必须来自 ml/ 训练管线并按
docs/model-contract.md 交接。

用法（仓库根目录执行，需要 Python 环境 + tensorflow）：
    python scripts/make_placeholder_model.py

输出（被 .gitignore 忽略，不进入 Git）：
    android/app/src/main/assets/models/model.tflite
    android/app/src/main/assets/models/labels.txt
    android/app/src/main/assets/models/metadata.json
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "android", "app", "src", "main", "assets", "models")
CATEGORIES_PATH = os.path.join(REPO_ROOT, "shared", "categories.example.json")

INPUT_SIZE = 224
MODEL_VERSION = "placeholder-random-v0"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_categories():
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("status") != "draft":
        # 冻结后应使用正式模型，占位模型仅供链路验证
        print("警告：类别清单已不是 draft 状态，占位模型标签仍按清单顺序生成", file=sys.stderr)
    return data["categories"]


def build_model(num_classes):
    import tensorflow as tf

    backbone = tf.keras.applications.MobileNetV2(
        input_shape=(INPUT_SIZE, INPUT_SIZE, 3),
        alpha=1.0,
        include_top=False,
        weights=None,  # 随机权重：占位用途
        pooling="avg",
    )
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax")(backbone.output)
    return tf.keras.Model(backbone.input, outputs)


def convert_to_tflite(model, workdir):
    import tensorflow as tf

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    try:
        return converter.convert()
    except Exception as exc:  # Keras 3 环境下的回退路径：先导出 SavedModel 再转换
        print(f"from_keras_model 失败（{exc}），改用 SavedModel 路径", file=sys.stderr)
        saved = os.path.join(workdir, "placeholder_saved_model")
        model.export(saved)
        converter = tf.lite.TFLiteConverter.from_saved_model(saved)
        return converter.convert()


def main():
    categories = load_categories()
    label_keys = [c["label_key"] for c in categories]
    os.makedirs(OUT_DIR, exist_ok=True)

    print("构建 10 类 MobileNetV2（随机权重）…")
    model = build_model(len(label_keys))

    print("转换为 tflite…")
    tflite_bytes = convert_to_tflite(model, OUT_DIR)

    model_path = os.path.join(OUT_DIR, "model.tflite")
    labels_path = os.path.join(OUT_DIR, "labels.txt")
    metadata_path = os.path.join(OUT_DIR, "metadata.json")
    with open(model_path, "wb") as f:
        f.write(tflite_bytes)
    with open(labels_path, "w", encoding="utf-8") as f:
        f.write("\n".join(label_keys) + "\n")

    metadata = {
        "status": "placeholder",
        "model_version": MODEL_VERSION,
        "model_file": "model.tflite",
        "sha256": sha256_file(model_path),
        "labels_file": "labels.txt",
        "labels_sha256": sha256_file(labels_path),
        "category_version": "draft-1",
        "data_version": "none",
        "experiment_id": "placeholder",
        "low_confidence_threshold": 0.60,
        "input": {
            "shape": f"1,{INPUT_SIZE},{INPUT_SIZE},3",
            "dtype": "float32",
            "color_order": "RGB",
            "orientation": "app applies EXIF before inference",
            "crop": "center",
            "resize": f"bilinear {INPUT_SIZE}",
            "normalization": "mobilenet_v2_minus1_1",
            "quantization": None,
        },
        "output": {
            "shape": f"1,{len(label_keys)}",
            "dtype": "float32",
            "interpretation": "softmax; index i == category id i",
            "quantization": None,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("已生成：")
    for p in (model_path, labels_path, metadata_path):
        print(" ", p, f"({os.path.getsize(p)} bytes)")


if __name__ == "__main__":
    main()
