# 环境与版本清单

状态：后端工程及MySQL记录入库已在Windows隔离环境验证，其余模块按实际结果填写。未填写的版本不代表已安装或兼容性验证通过。

| 模块 | 需要登记的信息 | 实际版本/设备 | 验证结果与日期 |
| --- | --- | --- | --- |
| Android | Android Studio、Kotlin及相关编译插件、JDK、Gradle、AGP、compile/min/target SDK | 待填写 | 待验证 |
| Android 依赖 | CameraX、Room、tflite/LiteRT 与网络库 | 待填写 | 待验证 |
| 真机 | 型号、Android 版本、处理器、内存 | 待填写 | 待验证 |
| 后端 | Python、Flask、SQLAlchemy、PyMySQL、依赖与配置加载方式 | Windows Python 3.11.4；Flask 3.1.3；Flask-SQLAlchemy 3.1.1；SQLAlchemy 2.0.54；PyMySQL 1.2.3；python-dotenv 1.2.4；Werkzeug 3.1.9；pytest 9.1.1；backend独立.venv；根目录.env及进程环境 | 2026-10-08：75项测试通过，3项SQLite下的MySQL专用用例跳过；真实MySQL并发、HTTP入库/重试/冲突及Flask重启后保留记录通过；Linux部署待验证 |
| 云端推理 | LiteRT Python运行时、模型与标签哈希、CPU线程与推理并发 | 待填写 | 待验证 |
| 数据库 | MySQL 版本、字符集、时区与备份方式 | 本机MySQL 8.0.25，隔离临时数据目录；InnoDB、utf8mb4_bin、UTC会话、DATETIME(3) | 2026-10-08：四表初始SQL、CLI建表/种子、CHECK/外键和UUID唯一约束验证；目标云端版本、账号及备份恢复待实施 |
| Web | 浏览器版本与支持范围 | 待填写 | 待验证 |
| 训练 | OS/WSL、Python、TensorFlow、Keras、依赖清单 | 待填写 | 待验证 |
| 各训练 PC | PC 标识、GPU、显存、驱动、实际 GPU 可用状态 | 待填写 | 待验证 |
| 云端 | Linux、Python、Gunicorn、Nginx、CPU、内存、磁盘余量 | 待填写 | 待验证 |

先验证小样本训练、模型转换和真机加载，再统一锁定依赖版本。各 PC 比较候选实验时使用相同环境和配置口径。实际 CPU/GPU 使用情况如实记录。

各模块提交构建配置、依赖清单和适用的锁定文件，补充复现命令；不提交本地环境目录、凭据或机器专用路径。

训练与云端服务使用独立Python环境。云端运行与手机相同的FP32 tflite，从一个Gunicorn worker和受控推理并发开始，记录实际内存和CPU；默认离线识别不依赖云端模型加载成功。模型更新后同步检查两端版本、哈希及预处理。
