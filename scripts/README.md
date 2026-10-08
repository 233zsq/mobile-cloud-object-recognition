# 辅助脚本

预留数据清单校验、文件哈希生成、数据库备份、环境检查与交付打包脚本。

## 现有脚本（Python，跨平台，仓库根目录运行）

| 脚本 | 用途 | 用法 | 依赖与输出 |
| --- | --- | --- | --- |
| `check_manifest.py` | 样本清单字段校验、文件存在与可解码检查、SHA-256 核对与回填、重复与模糊检测、类别/采集者统计 | `python scripts/check_manifest.py data/manifests/sample-manifest.csv [--check-files] [--fill-sha256] [--blur-threshold 50]` | 仅标准库；`--check-files` 需 Pillow 与 numpy。报告打印到终端，退出码 1 表示存在错误 |
| `split_dataset.py` | 按 object_id 分组做 60/20/20 训练/验证/测试划分并冻结清单（同实物不跨集合） | `python scripts/split_dataset.py data/manifests/sample-manifest.csv --data-version v1 [--seed 42] [--include-pending]` | 仅标准库。输出 `data/splits/<版本>/{train,validation,test}.csv` 与 `split-info.json`；已存在的版本目录拒绝覆盖 |

加入脚本时说明用途、运行目录、参数、依赖与输出位置。清单和文件路径相对仓库根目录；本机绝对路径和凭据通过本地配置提供，不能写死在脚本里。Windows 脚本使用 PowerShell，云端 Linux 脚本放在相应部署目录或在此明确运行平台。
