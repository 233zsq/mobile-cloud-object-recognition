# 模型放置位置

正式模型包由训练负责人按 `docs/model-contract.md` 交接。**当前正式发布包为
`models/releases/campus-gpu-v1/`**（冻结契约 rgb-letterbox-v1）。领取后把以下三个文件
复制到本目录：

- `model.tflite` —— 从交付归档/组内共享存储领取（8,939,040 字节，SHA-256 见 metadata）
- `labels.txt` —— 可直接从 `models/releases/campus-gpu-v1/labels.txt` 复制
- `metadata.json` —— 可直接从 `models/releases/campus-gpu-v1/metadata.json` 复制

三者必须来自同一发布包，App 会强制校验 SHA-256；混用旧包文件会加载失败。

## App 的校验规则（inference/ModelValidator.kt）

- 输入张量：4 维、批大小 1、正方形、3 通道、float32（量化模型暂不支持，需按契约另行适配）。
- 输出张量：2 维 `[1, 类别数]`，最后一维必须等于 labels.txt 行数。
- metadata.json 必须含 `model_version`；`sha256` 与 `labels_sha256` 填写即强制校验。
- `input.pixel_range` 必须为 `[0,255]`；归一化约定必须可解析。
- metadata 声明的 `input/output.shape` 必须与实际张量一致（支持数组与字符串两种写法）。
- 低置信阈值取 `low_confidence_threshold`（campus-gpu-v1 为 0.50），缺省 0.50。

校验失败时 App 停止识别并显示具体原因，不输出伪造分类结果（用例 T04）。

## 输入契约（rgb-letterbox-v1）

预处理实现见 `util/PreprocessMath.kt` 与 `inference/TfliteClassifier.kt`，必须与云端/PC
参考实现逐字一致：

1. EXIF 纠正方向；透明图先灰色(128)合成；推理路径按原始分辨率解码（不采样）。
2. `scale = 224 / max(宽,高)`，内框 `floor(原尺寸 × scale + 0.5)`。
3. 双线性 half-pixel、不额外抗锯齿；四邻域加权保留 float32，不取整为 uint8。
4. 灰色 128 居中补边、不裁剪，奇数余量在右/下。
5. 输入 `[1,224,224,3]` RGB float32、像素 0–255、little-endian（602112 字节）。
6. **归一化在模型内部**，端侧恒等；`inside model: x / 127.5 - 1` 即契约路径。

## 占位模型

链路验证可用占位模型（10 类随机权重 MobileNetV2，输入输出与契约一致，
**不得用于准确率结论**；随机权重输出接近均匀，正好用于联调低置信与纠错流程）。
在仓库根目录执行：

```bash
python scripts/make_placeholder_model.py
```

脚本会按冻结类别清单生成本目录的 model.tflite / labels.txt / metadata.json。

## 端云一致性验证（交接要求）

发布包附带 20 张样例（`examples/`，图片+参考张量+期望分数）。按要求需分别在
「直接喂参考张量」与「从图片走本机预处理」两种模式下回传结果，供
`scripts/make-handover-report.py` 与 `python -m recognition verify` 核对
（Top-1 一致、分数差 ≤0.001；图片模式另需输入像素差 ≤0.001）。模板见
`shared/device-results/`。该项依赖真机执行，当前状态：待执行。