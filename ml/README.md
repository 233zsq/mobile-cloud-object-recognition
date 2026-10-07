# 模型训练与导出

负责人：模型训练负责人。采用 TensorFlow/Keras 与 MobileNetV2 迁移学习。

已实现可安装的 `recognition` 包及以下训练、采集、审核、评估与交接入口。Windows CPU 工具链已实测；WSL GPU 环境需系统组件安装与重启后验证。实际状态见 `experiments/reports/implementation-status.json`，训练环境版本见 `docs/environment.md`。

实际配置模板为 `configs/baseline.json`；`configs/pilot-cpu.json` 显式引用首个真实照片试验集。旧的 `baseline.example.json` 保留作原始模板，不作为实际运行配置。

- 数据由 `data/manifests/`、`data/splits/` 的清单读取；划分按实物分组，增强仅用于训练集。
- 按学习率、Dropout、微调范围逐阶段比较候选；使用验证集选参，选定配置至少复核一次。
- 测试集用于冻结后的独立评估，不参与选参、阈值选择或量化校准。
- 实验元数据使用 `experiments/experiment-log.template.csv`，日志与检查点放在对应目录。
- 最终发布包放到 `models/releases/<模型版本>/`，按 `docs/model-contract.md` 交接。

## 安装与环境验证

Windows CPU（PowerShell，先创建独立环境）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ml/requirements-windows-cpu.lock
.\.venv\Scripts\python.exe -m pip install -e ml --no-deps
.\.venv\Scripts\python.exe -m recognition doctor
.\.venv\Scripts\python.exe -m pytest ml/tests -q -c ml/pytest.ini
```

本机Python launcher存在异常，已验证解释器为
`C:\Users\zhens\AppData\Local\Programs\Python\Python313\python.exe`。
其他PC优先使用Python 3.12；Windows锁文件反映实际Python 3.13 CPU环境。

WSL2/Ubuntu 24.04：管理员运行 `scripts/setup-wsl-admin.ps1`，按其提示安排重启、
更新WSL、安装Ubuntu和创建Linux账号。Git Bash可用
`bash scripts/wsl-setup-wizard.sh` 逐步完成这些人工步骤。
Ubuntu安装python3.12-venv后运行 `bash scripts/setup-ml-wsl.sh`。
该脚本验证GPU可见性，并实测冻结骨干和最大微调范围下batch32（显存不足时统一16）的
梯度更新、优化器保存恢复及FP32内置算子转换，保存显存峰值。随后执行smoke和测试。
单独重测：`python -m recognition doctor --training-check --require-gpu`。

当前新增冻结数据为 `campus-public-expanded-v1`，659张公开训练、218张公开验证。
WSL环境安装可运行 `bash scripts/setup-ml-wsl.sh campus-public-expanded-v1`，
生成 `ml/configs/wsl-campus-public-expanded-v1.json`，使用实测推荐公共batch。
然后运行 `./.venv-wsl/bin/python scripts/run-ml-campaign.py --config ml/configs/wsl-campus-public-expanded-v1.json --campaign expanded-gpu-v1 --version campus-gpu-v1 --formal`。
完整GPU训练前必须通过环境梯度/显存检查；CPU版本保持试验状态。

独立运行时按 `requirements-runtime.txt` 安装，详见 `docs/ml-handover.md`。
本机独立Windows环境锁为 `requirements-windows-runtime.lock`，已确认不含TensorFlow。

## 数据采集与审核

```bash
python -m recognition collect --provider commons --per-class 120
python -m recognition audit --manifest data/manifests/public-candidates.csv
```

Open Images默认读取并缓存官方小型validation来源索引（该公开来源子集可进入本项目训练/验证，
与独立实拍测试无关）。累计索引传输预算1.2GiB，包含首次train索引扫描；不重复扫描大型索引。
`--source-split train`仅用于尚未扫描过索引且预算足够的首次采集。

候选清单默认 pending，审核预览位于 `experiments/reports/audit/`。
逐图查看后，填写 `data/manifests/public-review-decisions.csv`，再执行：

```bash
python -m recognition audit --manifest data/manifests/public-candidates.csv \
  --decisions data/manifests/public-review-decisions.csv
python -m recognition split --manifest data/manifests/public-candidates.csv \
  --version campus-public-v1 --seed 42
```

收集进程运行时不要修改其候选清单；先复制快照进行预览审核，待收集结束后合并决定。
冻结数据版本不可覆盖，修改图片或清单后所有训练入口拒绝继续。
近重复组/同物品系列共享group_id；公开照片无法确认实物ID时留空。
缺口先扩大Commons候选至每类240张，再按需要运行Open Images有框类别回退，例如：

```bash
python -m recognition collect --provider openimages --categories pencil_case --per-class 120
```

Open Images候选独立保存为openimages-candidates.csv，可用audit --merge-manifests生成
public-reviewed.csv合并审核快照，避免两个采集进程覆盖同一清单。
首次补笔袋扫描约1.015GB的框类别人工标签及图片元数据，后续使用约26MB的缓存validation索引。
不会下载全量框坐标或5GB全索引。
后续可使用`--source-split public-test`读取官方公开test来源的小型标签、图片元数据和有框索引，
仅挑选单个主要目标候选；它仍属于本项目公开训练/验证来源，不是独立实拍测试。
Commons缩略图使用官方标准960/500/330/250尺寸，并严格小于原图宽度，避免未缩放原图的限流。
尺寸依据：https://www.mediawiki.org/wiki/Common_thumbnail_sizes 。
补拍训练照片与实拍测试照片分开，采集与测试规则见交接说明。

## 基线与阶段调参

复制 `configs/baseline.json`，填写实际冻结的data_version，保留category_version。
各阶段最多20轮，使用验证宏平均F1最佳检查点，验证损失早停patience=3。

```bash
python -m recognition train --config ml/configs/campus-v1.json --experiment campus-baseline
python -m recognition sweep --config ml/configs/campus-v1.json \
  --campaign campus-v1 --stage learning_rate --execute
python -m recognition summarize --jobs experiments/reports/campus-v1/learning_rate-jobs.json
python -m recognition sweep --config ml/configs/campus-v1.json --campaign campus-v1 \
  --stage dropout --previous experiments/reports/campus-v1/learning_rate-summary.json --execute
python -m recognition summarize --jobs experiments/reports/campus-v1/dropout-jobs.json
python -m recognition sweep --config ml/configs/campus-v1.json --campaign campus-v1 \
  --stage fine_tune --previous experiments/reports/campus-v1/dropout-summary.json --execute
python -m recognition summarize --jobs experiments/reports/campus-v1/fine_tune-jobs.json
```

去掉--execute生成四PC任务文件（`pc-tasks/`），第四台等待胜出流程后复核；各PC按jobs中的config和
initial_checkpoint执行train，回传result.json和对应best.keras。
各PC必须使用相同冻结数据、依赖和代码；设备耗时单独记录，不据此宣称并行加速。

暂停后用原config、实验ID及原initial-checkpoint运行 `train --resume`。
每轮保存模型和优化器到epoch编号检查点，再原子更新进度指针及哈希；latest.keras为便利副本，best.keras用于候选选择。代码或配置变化须另开run。
北京时间23:00至06:00暂停长训练，预估下一轮越过23:00时提前停止。
重复执行相同sweep可跳过完整结果并恢复暂停run。

## 复核、导出与性能

对summary中胜出experiment的result.json执行：

```bash
python -m recognition reproduce --result experiments/reports/<winner>/result.json --seed 43
python -m recognition export --result experiments/reports/<winner>/result.json \
  --version campus-v1 --formal --reproduction experiments/reports/<winner>-repeat43/result.json
python -m recognition verify --release models/releases/campus-v1
python -m recognition benchmark --release models/releases/campus-v1 --threads 1
```

复核会重新训练分类头及所选微调阶段，保留seed43结果。F1差异超过0.05时追加seed44
并分析差异；export另外提供--additional-reproduction指向seed44结果。
使用新的模型版本保存发布，不覆盖旧包。
低置信阈值只由验证集决定；模型输出Softmax分数不等于经过校准的正确率。

快速完整验证：`python -m recognition smoke --id <unique-id> --epochs 1`。
该命令生成明确标记的合成fixture，训练、保存、转换、同图验证和CPU测速；
其accuracy不能作为真实物品识别成绩，不能导出为正式发布包。
Windows TensorFlow原生SavedModel IO在中文路径有问题，导出用ASCII临时目录完成，
然后复制回仓库；读取TFLite使用model_content避免原生路径编码问题。
