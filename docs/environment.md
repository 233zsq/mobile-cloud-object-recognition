# 环境与版本清单

状态：后端及MySQL记录入库已在Windows隔离环境和腾讯云Linux环境验证，服务器部署及公网HTTPS验收通过。其他模块按实际结果填写；未填写的版本不代表已验证。

| 模块 | 需要登记的信息 | 实际版本/设备 | 验证结果与日期 |
| --- | --- | --- | --- |
| Android | Android Studio、Kotlin及相关编译插件、JDK、Gradle、AGP、compile/min/target SDK | 待填写 | 待验证 |
| Android 依赖 | CameraX、Room、tflite/LiteRT 与网络库 | 待填写 | 待验证 |
| 真机 | 型号、Android 版本、处理器、内存 | 待填写 | 待验证 |
| 后端 | Python、Flask、SQLAlchemy、PyMySQL、依赖与配置加载方式 | Windows Python 3.11.4、Linux Python 3.14.4；Flask 3.1.3；Flask-SQLAlchemy 3.1.1；SQLAlchemy 2.0.54；PyMySQL 1.2.3；python-dotenv 1.2.4；Werkzeug 3.1.9；pytest 9.1.1；独立.venv | 2026-10-08：两种环境各75项通过、3项SQLite参数下的MySQL专用用例跳过；真实MySQL、并发、HTTP入库/重试/冲突及服务重启持久性通过 |
| 云端推理 | LiteRT Python运行时、模型与标签哈希、CPU线程与推理并发 | 待填写 | 待验证 |
| 数据库 | MySQL 版本、字符集、时区与备份方式 | 本机隔离MySQL 8.0.25；云端MySQL 8.4.11；InnoDB、utf8mb4_bin、UTC会话、DATETIME(3)；每日备份保留七天 | 2026-10-08：四表SQL、种子、约束及受限运行账号已验证；备份和隔离恢复通过 |
| Web | 浏览器版本与支持范围 | 待填写 | 待验证 |
| 训练 | OS/WSL、Python、TensorFlow、Keras、依赖清单 | 待填写 | 待验证 |
| 各训练 PC | PC 标识、GPU、显存、驱动、实际 GPU 可用状态 | 待填写 | 待验证 |
| 云端 | Linux、Python、Gunicorn、Nginx、CPU、内存、磁盘余量 | Ubuntu 26.04 LTS x86_64；Python 3.14.4；Gunicorn 25.3.0；Nginx 1.28.3；2核、约4GB内存、42GiB磁盘余量 | 2026-10-08：systemd服务及每日备份启用；IP自签名HTTPS、Bearer保护和公网201/200/409通过；云端模型尚未加载 |

先验证小样本训练、模型转换和真机加载，再统一锁定依赖版本。各 PC 比较候选实验时使用相同环境和配置口径。实际 CPU/GPU 使用情况如实记录。

各模块提交构建配置、依赖清单和适用的锁定文件，补充复现命令；不提交本地环境目录或凭据。部署模板中的服务器账号和路径在 [部署说明](../deploy/README.md) 明示。

训练与云端服务使用独立Python环境。云端运行与手机相同的FP32 tflite，从一个Gunicorn worker和受控推理并发开始，记录实际内存和CPU；默认离线识别不依赖云端模型加载成功。模型更新后同步检查两端版本、哈希及预处理。
