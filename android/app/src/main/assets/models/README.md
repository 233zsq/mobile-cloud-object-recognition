# 模型放置位置

正式模型包由训练负责人按 `docs/model-contract.md` 交接，领取后把以下三个文件复制到本目录
（`model_file` 与 `labels_file` 名称以 metadata.json 为准）：

- `model.tflite`
- `labels.txt`
- `metadata.json`

本目录的模型二进制被根 `.gitignore`（`*.tflite`）忽略，不进入 Git。

## App 的校验规则（inference/ModelValidator.kt）

- 输入张量：4 维、批大小 1、正方形、3 通道、float32（量化模型暂不支持，需按契约另行适配）。
- 输出张量：2 维 `[1, 类别数]`，最后一维必须等于 labels.txt 行数。
- metadata.json 必须含 `model_version`；`sha256` 与 `labels_sha256` 若填写则强制校验。
- 低置信阈值取 `low_confidence_threshold`，缺省 0.60。
- 归一化取 `input.normalization`：`mobilenet_v2_minus1_1`（x/127.5-1，默认）或 `unit_0_1`。

校验失败时 App 停止识别并显示具体原因，不输出伪造分类结果（用例 T04）。

## 占位模型

联调验证链路可用占位模型（10 类随机权重 MobileNetV2，输入输出规格与契约一致，
不能用于准确率结论）。在仓库根目录执行：

```bash
python scripts/make_placeholder_model.py
```

脚本会生成本目录的 model.tflite / labels.txt / metadata.json。
