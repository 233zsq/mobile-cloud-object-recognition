# 环境与版本清单

状态：待验证填写。计划书没有锁定完整版本，此表不代表已安装或兼容性验证通过。

## 训练 PC 登记（组长汇总，10月8日首日完成）

| PC 标识 | 日常使用人 | CPU | GPU | 显存 | 驱动版本 | 系统 / WSL2 情况 | TensorFlow 可见 GPU | 登记日期 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PC-A | 赵高剑 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待验证 | |
| PC-B | 鲁涵宇 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待验证 | |
| PC-C | 刘亮 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待验证 | |
| PC-D | 张弓羿 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待验证 | |

GPU 可用性验证命令（WSL2/Linux 的 Python 环境内执行，输出截图或文本随登记保存）：

```bash
python -c "import tensorflow as tf; print(tf.__version__); print(tf.config.list_physical_devices('GPU'))"
```

原生 Windows 上现代 TensorFlow 默认不可用 GPU，优先 WSL2 或 Linux 方案；若 GPU 未跑通，登记为"CPU 基线"并注明，不阻塞 App 联调。

| 模块 | 需要登记的信息 | 实际版本/设备 | 验证结果与日期 |
| --- | --- | --- | --- |
| Android | Android Studio、Kotlin及相关编译插件、JDK、Gradle、AGP、compile/min/target SDK | 待填写 | 待验证 |
| Android 依赖 | CameraX、Room、tflite/LiteRT 与网络库 | 待填写 | 待验证 |
| 真机 | 型号、Android 版本、处理器、内存 | 待填写 | 待验证 |
| 后端 | Python、Flask、SQLAlchemy、PyMySQL、依赖与配置加载方式 | 待填写 | 待验证 |
| 云端推理 | LiteRT Python运行时、模型与标签哈希、CPU线程与推理并发 | 待填写 | 待验证 |
| 数据库 | MySQL 版本、字符集、时区与备份方式 | 待填写 | 待验证 |
| Web | 浏览器版本与支持范围 | 待填写 | 待验证 |
| 训练 | OS/WSL、Python、TensorFlow、Keras、依赖清单 | 待填写 | 待验证 |
| 各训练 PC | PC 标识、GPU、显存、驱动、实际 GPU 可用状态 | 待填写 | 待验证 |
| 云端 | Linux、Python、Gunicorn、Nginx、CPU、内存、磁盘余量 | 待填写 | 待验证 |

先验证小样本训练、模型转换和真机加载，再统一锁定依赖版本。各 PC 比较候选实验时使用相同环境和配置口径。实际 CPU/GPU 使用情况如实记录。

各模块提交构建配置、依赖清单和适用的锁定文件，补充复现命令；不提交本地环境目录、凭据或机器专用路径。

训练与云端服务使用独立Python环境。云端运行与手机相同的FP32 tflite，从一个Gunicorn worker和受控推理并发开始，记录实际内存和CPU；默认离线识别不依赖云端模型加载成功。模型更新后同步检查两端版本、哈希及预处理。
