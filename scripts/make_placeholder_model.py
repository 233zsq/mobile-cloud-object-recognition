#!/usr/bin/env python
"""生成占位验证模型（10 类随机权重 MobileNetV2，严格遵循契约 rgb-letterbox-v1）。

用途：在正式发布包（models/releases/campus-gpu-v1）的 model.tflite 领取到位之前，
验证 Android 端「加载-校验-预处理-推理-显示」链路。随机权重输出接近均匀分布，
恰好用于联调低置信提示与人工纠错流程。

输入契约与正式模型一致：
- 输入 [1,224,224,3] RGB float32，像素 0–255；
- 归一化 x/127.5-1 做在模型内部（Rescaling 层）；
- 输出 [1,10] float32 Softmax，索引与 shared/categories.json 一致。

注意：该模型不能用于任何准确率结论；正式模型必须来自 ml/ 训练管线并按
docs/model-contract.md 交接。

用法（仓库根目录执行，需要 Python 环境 + tensorflow）：
    python scripts/make_placeholder_model.py

输出（模型二进制被 .gitignore 忽略，不进入 Git）：
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
CATEGORIES_PATH = os.path.join(REPO_ROOT, "shared", "categories.json")

INPUT_SIZE = 224
MODEL_VERSION = "placeholder-letterbox-v1"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_categories():
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def build_model(num_classes):
    import tensorflow as tf

    inputs = tf.keras.Input(shape=(INPUT_SIZE, INPUT_SIZE, 3), dtype=tf.float32, name="image")
    # 契约：归一化在模型内部完成，端侧直送 0–255 原始像素
    x = tf.keras.layers.Rescaling(scale=1.0 / 127.5, offset=-1.0, name="inside_model_normalization")(inputs)
    backbone = tf.keras.applications.MobileNetV2(
        input_shape=(INPUT_SIZE, INPUT_SIZE, 3),
        alpha=1.0,
        include_top=False,
        weights=None,  # 随机权重：占位用途
        pooling="avg",
    )
    features = backbone(x)
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax", name="predictions")(features)
    return tf.keras.Model(inputs, outputs)


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
    categories_file = load_categories()
    categories = categories_file["categories"]
    label_keys = [c["label_key"] for c in categories]
    if categories_file.get("status") != "frozen":
        print("警告：shared/categories.json 不是 frozen 状态，请与组长确认类别版本", file=sys.stderr)
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"构建 {len(label_keys)} 类 MobileNetV2（随机权重，归一化在模型内部）…")
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

    # 字段与正式发布包 models/releases/campus-gpu-v1/metadata.json 对齐
    metadata = {
        "status": "placeholder",
        "model_version": MODEL_VERSION,
        "model_file": "model.tflite",
        "sha256": sha256_file(model_path),
        "labels_file": "labels.txt",
        "labels_sha256": sha256_file(labels_path),
        "category_version": categories_file.get("category_version", "campus-10-v2"),
        "categories": categories,
        "data_version": "none",
        "experiment_id": "placeholder",
        "input": {
            "version": "rgb-letterbox-v1",
            "orientation": "EXIF transpose",
            "color_order": "RGB",
            "shape": [1, INPUT_SIZE, INPUT_SIZE, 3],
            "dtype": "float32",
            "pixel_range": [0, 255],
            "crop": "none",
            "resize": "bilinear half_pixel_centers; antialias=false; round half up",
            "padding": "center; RGB 128; odd remainder right/bottom",
            "normalization": "inside model: x / 127.5 - 1",
            "byte_order": "little-endian",
        },
        "output": {
            "shape": [1, len(label_keys)],
            "dtype": "float32",
            "interpretation": "softmax",
        },
        "low_confidence_threshold": 0.5,
        "threshold_status": "placeholder",
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