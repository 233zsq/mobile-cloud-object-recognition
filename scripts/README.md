# 辅助脚本

模型训练环境脚本均从仓库根目录运行：

- Windows管理员PowerShell：`./scripts/setup-wsl-admin.ps1` 启用WSL及虚拟机平台，不自动重启；系统要求重启时先保存工作。
- Windows管理员PowerShell：`./scripts/install-wsl-ubuntu.ps1` 安装WSL和Ubuntu24.04但不自动启动Linux、不重启，保存实际返回码；首次Linux账号由本人创建。
- Git Bash：`bash scripts/wsl-setup-wizard.sh` 引导完成管理员安装、重启和首次Linux账号创建。
- Ubuntu 24.04：`bash scripts/setup-ml-wsl.sh` 建立Python3.12训练及独立LiteRT环境，锁定实际版本，验证GPU梯度更新、显存、模型保存及FP32转换。显存不足时将公共batch统一改为16，重新生成全部候选。

`ML_TRAIN_ENV`、`ML_RUNTIME_ENV` 可分别指定Linux环境目录；脚本解析目录链接，拒绝两个目录实际相同，并检查独立推理环境中没有TensorFlow。仓库在Windows挂载盘上时，优先把环境放在Linux文件系统，具体示例见 `ml/README.md`。
每个新的Ubuntu终端先 `source scripts/activate-ml-wsl.sh`，加载训练解释器及NVIDIA动态库路径，再运行训练入口。自定义路径时使用相同的 `ML_TRAIN_ENV`。此设置只影响当前终端；独立LiteRT环境仍使用它自己的解释器。

数据、训练、哈希、评估和模型交接使用安装后的 `python -m recognition`，命令详见 `ml/README.md`。本期不包含数据库备份脚本。

完成同一数据版本的训练后，运行 `python scripts/package-ml-delivery.py --release models/releases/<version>`。
脚本校验发布模型、冻结清单和图片字节，打包源代码、环境锁、实际照片、检查点与交接样例，排除虚拟环境和个人计划书。
归档位于本机 `backups/`，包含SHA-256清单，并逐项核验压缩包内容；这只是本地交付副本，仍需复制到组内独立备份存储。

`make-handover-report.py --release models/releases/<version> --mode reference_tensor|image_chain --out <结果JSON>`
生成全部20张样例的空白结果表，由Android或云端负责人填写实际分数和设备信息。
随后用 `python -m recognition verify --release ... --external-report ...` 核对并保存通过或失败记录。
`write-ml-report.py` 只重生成历史CPU先导章节 `docs/ml-experiments.md`，不修改当前发布状态；未来正式实验应使用各阶段summarize输出重新整理实际指标。
`write-expanded-ml-report.py` 重生成已完成的877张公开照片CPU历史实验章节，保留该版本的类别和实验记录，不修改当前模型选择、发布状态、哈希或验收进度。

独立LiteRT环境运行 `check-local-runtime.py --release models/releases/<version> --run-id <唯一ID>`，
实际检查20张参考张量和20次图片预处理，并保存没有安装/导入TensorFlow的记录。
这只验证本机运行时和回传工具，Android/真实云端另交实际记录。
`record-source-commit.py --commit <提交>` 逐文件核对提交与训练模块字节，保存源码摘要，不能把不匹配的提交作为复现版本。

`run-ml-campaign.py --config ml/configs/<数据版本>.json --campaign <唯一实验ID> --version <模型版本>`
顺序完成三阶段、种子43复核（差异大时追加44）、试验导出、验证评估和本机CPU测速。
GPU环境预跑和正式训练完成后可加 `--formal`；CPU试验不能标为正式GPU成果。
达到夜间停止窗口时保存检查点，同一命令可在次日继续；修改代码或配置时使用新的campaign。

## 样本采集辅助脚本（Python，跨平台，仓库根目录运行）

| 脚本 | 用途 | 用法 | 依赖与输出 |
| --- | --- | --- | --- |
| `check_manifest.py` | 样本清单字段校验、文件存在与可解码检查、SHA-256 核对与回填、重复与模糊检测、类别/采集者统计 | `python scripts/check_manifest.py data/manifests/sample-manifest.csv [--check-files] [--fill-sha256] [--blur-threshold 50]` | 仅标准库；`--check-files` 需 Pillow 与 numpy。报告打印到终端，退出码 1 表示存在错误 |
| `split_dataset.py` | 按 object_id 分组做 60/20/20 训练/验证/测试划分并冻结清单（同实物不跨集合） | `python scripts/split_dataset.py data/manifests/sample-manifest.csv --data-version v1 [--seed 42] [--include-pending]` | 仅标准库。输出 `data/splits/<版本>/{train,validation,test}.csv` 与 `split-info.json`；已存在的版本目录拒绝覆盖 |

两个脚本共用清单读取规则：表头必须与模板一致，每行字段数必须完整，读取时统一去除字段首尾空白。因此 `cup-01` 与 `cup-01 ` 会作为同一实物统计、划分，冻结清单中的字段也使用去除空白后的值。划分不改写源清单。

SHA-256 回填只在检查无错误时执行（警告不阻止回填）：先完整写入同目录临时文件，再替换原清单；校验或写入失败时不覆盖原文件。

回归验证（仅标准库，仓库根目录运行）：

```bash
python -m unittest discover -s tests -p test_data_scripts.py -v
```

加入脚本时说明用途、运行目录、参数、依赖与输出位置。清单和文件路径相对仓库根目录；本机绝对路径和凭据通过本地配置提供，不能写死在脚本里。Windows 脚本使用 PowerShell，云端 Linux 脚本放在相应部署目录或在此明确运行平台。
