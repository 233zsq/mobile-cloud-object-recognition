# 环境与版本清单

状态：待验证填写。计划书没有锁定完整版本，此表不代表已安装或兼容性验证通过。

| 模块 | 需要登记的信息 | 实际版本/设备 | 验证结果与日期 |
| --- | --- | --- | --- |
| Android | Android Studio、Kotlin及相关编译插件、JDK、Gradle、AGP、compile/min/target SDK | 开发命令行 JDK 24.0.1；Gradle 9.4.1；AGP 9.2.1；Kotlin 2.2.10；KSP 2.3.12；compileSdk 37 / minSdk 26 / targetSdk 36（构建通过 2026-10-07） | 构建+单测通过，待真机安装验证 |
| Android 依赖 | CameraX、Room、tflite/LiteRT 与网络库 | CameraX 1.6.2；Room 2.8.5（KSP 2.3.12）；LiteRT 1.4.1（`org.tensorflow.lite` API）；Retrofit 3.0.0 + OkHttp 5.5.0；WorkManager 2.12.0；DataStore 1.2.1；kotlinx-serialization 1.11.0；Compose BOM 2026.09.00（见 android/gradle/libs.versions.toml） | 版本锁定待真机回归后冻结 |
| 真机 | 型号、Android 版本、处理器、内存 | 待填写（Android 8.0+ 均在兼容范围，minSdk 26） | 待验证 |
| 后端 | Python、Flask、SQLAlchemy、PyMySQL、依赖与配置加载方式 | 待填写 | 待验证 |
| 云端推理 | LiteRT Python运行时、模型与标签哈希、CPU线程与推理并发 | 待填写 | 待验证 |
| 数据库 | MySQL 版本、字符集、时区与备份方式 | 待填写 | 待验证 |
| Web | 浏览器版本与支持范围 | 待填写 | 待验证 |
| 训练 | OS/WSL、Python、TensorFlow、Keras、依赖清单 | 待填写 | 待验证 |
| 各训练 PC | PC 标识、GPU、显存、驱动、实际 GPU 可用状态 | 待填写 | 待验证 |
| 云端 | Linux、Python、Gunicorn、Nginx、CPU、内存、磁盘余量 | 待填写 | 待验证 |

先验证小样本训练、模型转换和真机加载，再统一锁定依赖版本。各 PC 比较候选实验时使用相同环境和配置口径。实际 CPU/GPU 使用情况如实记录。

各模块提交构建配置、依赖清单和适用的锁定文件，补充复现命令；不提交本地环境目录、凭据或机器专用路径。

### 本机已知问题（开发机，2026-10-07）

- **系统 PATH 含有一个多余的双引号**（`E:\WEB\apache-tomcat-8.5.69\lib"`），导致 Gradle 单元测试 worker 的
  `-Djava.library.path` 参数被引号拆坏，报 `ClassNotFoundException: Files\Git\cmd;D:\node;C:\Program`。
  会话内用 `PATH=$(echo "$PATH" | tr -d '"')` 清洗后可正常构建；建议尽快在系统环境变量中修复该条目，
  否则 Android Studio 内运行单元测试也会遇到同样问题。
- Python 环境安装 TensorFlow 需用 Windows 专用包：`pip install tensorflow-intel`（2.18.0 验证可用，
  `pip install tensorflow` 在原生 Windows 无新版本 wheel）。

训练与云端服务使用独立Python环境。云端运行与手机相同的FP32 tflite，从一个Gunicorn worker和受控推理并发开始，记录实际内存和CPU；默认离线识别不依赖云端模型加载成功。模型更新后同步检查两端版本、哈希及预处理。
