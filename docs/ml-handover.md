# 模型训练交接与实拍评估

## 当前交付状态

当前选定试验包为 `models/releases/expanded-cpu-v1/`：ImageNet
MobileNetV2 + 10 类头，659张公开训练照片、218张公开验证照片。
验证准确率90.37%、宏平均F1=0.8993，仅为公开验证集成绩。FP32文件8,939,040字节，
完整验证集Keras/TFLite最大分数差3.34e-6，Top-1一致；20张参考张量和20次图片链路
已在不含TensorFlow的LiteRT2.2.0独立环境实际复核，最大分数差0。
种子43完整复核宏F1=0.8842，差0.01509；低置信阈值0.50。分阶段记录见 `ml-expanded-experiments.md`。
本机CPU单线程、20次预热/100次计时：纯推理P50/P95=19.49/31.18ms，
预处理加推理=43.73/64.26ms，循环全部20张样例。这些不是手机或真实云端结果。
模型SHA-256：`7bde6b570248b2795f6165a12d7bf763615ae2763c16ed17862da8cac5bc3558`。
源码提交为`a64f5f7`，与训练源码摘要逐文件核对通过。
旧版514张数据先导结果保留在 `ml-experiments.md`，两版划分不同，不直接比较提升率。
类别版本campus-10-v2，键盘只包含独立外接计算机键盘。
较早的 `smoke-20261007-export-v3/` 和 `smoke-20261007-current/` 使用合成fixture，
只作加载、输入、哈希和一致性验证，不作真实物品识别成绩。
正式训练、真实独立测试、Android 性能和真实腾讯云性能均单独登记。
实际进度见 `experiments/reports/implementation-status.json`，禁止把本机 CPU
耗时当作手机或腾讯云结果。

## 手机与云端共同输入

1. 处理 EXIF 方向，转为 RGB；透明图片先在灰色背景合成。
2. `scale = 224 / max(width, height)`；缩放宽高 `floor(original * scale + 0.5)`。
3. 使用双线性、half-pixel 坐标，不额外抗锯齿：
   `source_x = clamp((target_x + 0.5) * source_width / target_width - 0.5)`。
   Y 同理，四邻域通道加权结果保留 float32，不先取整为 uint8。
4. 居中补边 RGB=(128,128,128)，奇数余量位于右侧/下侧。
5. 输入 `[1,224,224,3]` RGB float32，像素0–255，模型内部已做 `x/127.5-1`。
6. 输出 `[1,10]` float32 Softmax，索引由冻结类别表确定。

参考实现 `recognition.preprocessing.preprocess` 不依赖 TensorFlow。
先用 `examples/*.bin` 直接喂模型，再用对应图片验证自己的预处理。
bin 为连续 NHWC little-endian float32，共 602112 字节。
`examples/manifest.json` 提供每个文件哈希、期望分数、类别及来源署名。

Python CPU 接入：

```python
from recognition.inference import LiteRunner
runner = LiteRunner("models/releases/<version>", threads=1)
result = runner.predict_image("photo.jpg")
```

Interpreter 非线程安全。后端应限制推理并发或独立实例；本模块不实现 Flask 接口。
部署按 `ml/requirements-runtime.txt` 安装运行时；使用项目包时可 `pip install -e ml --no-deps`，
LiteRunner 本身只需要 NumPy、Pillow 和 ai-edge-litert。

## 实拍测试采集

- 10类，每类至少20张，建议5件不同实物各4张。
- 全景保留主要主体，改变背景、角度和照明；不要只拍同一件物品的连续连拍。
- 记录真实 `object_id`、采集场次、采集者和类别；不同实物不要共享ID。
- `source_dataset` 填 `field`，清单路径相对仓库根目录。
- 补拍训练物品和测试物品使用不同实物ID；测试物品保持独立。
- 模型、几何处理和阈值冻结后才执行最终评估；训练人员不能用测试指标选参。

填写 `data/manifests/field-test.template.csv` 后运行 audit，由组长确认标签。
审核决定文件的列为 `sample_id,category_id,review_status,review_reason,group_id,object_id`。
审核不会自动把候选标为 approved。审核过程中发现照片损坏或哈希改变不能强行通过。

冻结独立测试版本，不修改训练/验证数据：

```bash
python -m recognition split --test-only --manifest data/manifests/field-test.csv \
  --training-version campus-public-expanded-v1 --version campus-field-v1
python -m recognition evaluate --release models/releases/campus-v1 --split test \
  --test-version campus-field-v1 --confirm-model-hash <metadata中的sha256>
```

正式测试只接受 frozen 发布包、approved 实拍照片及真实物品ID，每类至少20张。
结果记录模型/清单哈希、10类指标、混淆矩阵和预测明细。保留首次测试证据；
后续修改模型需使用新的独立测试版本，不把失败测试照片转作训练。

## 真机与云端实测

各端先预热20次，再测至少100次；登记硬件、OS、运行时、线程、模型版本及哈希。
分别测纯推理、预处理加推理P50/P95。手机还需记录上传至返回的网络总等待。
腾讯云部署负责人另外记录CPU、内存、并发和失败率。

Android/真实云端检查项在 `tests/model-handover-cases.csv`，未实测保持 pending。

## 回传同图记录

每个端分别提交两份记录，先直接使用参考张量，再从图片生成输入：

```bash
python scripts/make-handover-report.py --release models/releases/expanded-cpu-v1 \
  --mode reference_tensor --out experiments/reports/android-tensor.json
python scripts/make-handover-report.py --release models/releases/expanded-cpu-v1 \
  --mode image_chain --out experiments/reports/android-image.json
python -m recognition verify --release models/releases/expanded-cpu-v1 \
  --external-report experiments/reports/android-tensor.json
```

模板分数留空，填写实际10类输出、设备、运行时、线程及唯一run_id。
reference_tensor中的哈希须从实际喂入的602112字节计算；image_chain须保存实际预处理
little-endian float32输入文件，tensor_file相对结果JSON目录。两个模式都须覆盖全部20张样例。
核对要求Top-1一致、最大分数差≤0.001；图片模式额外要求输入像素最大差≤0.001。
结果保存在 `experiments/reports/consistency/<模型版本>/`，失败也保留差异记录。
JPEG解码或插值差异需要先定位，不能把失败记录标成通过；输入范围检查本身不能发现所有重复归一化，
必须与参考张量比较。核对通过只证明该端同图一致性，手机性能和独立测试仍单独验收。

## 复现、备份和GPU续作

本地交付归档为 `backups/expanded-cpu-v1-delivery.zip`，归档SHA-256及逐项核验记录在
`experiments/reports/delivery/expanded-cpu-v1/archive.json`，包内有 `delivery-files.json`。
包含877张实际训练/验证照片、冻结清单、源码、依赖锁、各候选最佳及续训检查点、
使用过的ImageNet初始权重和交接样例。虚拟环境需按锁文件重建；未提供组内异机备份位置。

将归档解压到新的工作目录，先核对归档及包内文件哈希，再按 `ml/README.md` 安装。
使用相同Python、依赖锁、数据和源码，在新campaign/model版本运行，保留旧实验和评估。
本机可执行：`./.venv/Scripts/python.exe scripts/run-ml-campaign.py --config ml/configs/public-expanded-cpu.json --campaign <新ID> --version <新版本>`。

WSL3.0.1和系统组件已安装，重启后先核对 `wsl --status`。
安装Ubuntu24.04并创建本人Linux账号后，在仓库目录运行
`bash scripts/setup-ml-wsl.sh campus-public-expanded-v1`，由GPU实测生成公共batch配置。
执行 `./.venv-wsl/bin/python scripts/run-ml-campaign.py --config ml/configs/wsl-campus-public-expanded-v1.json --campaign expanded-gpu-v1 --version campus-gpu-v1 --formal`。
GPU梯度/显存检查和完整训练完成前，现有CPU试验包保持experimental。
