# 环境与版本清单

状态：后端及MySQL记录入库已在Windows隔离环境和腾讯云Linux环境验证，服务器部署及公网HTTPS验收通过。其他模块按实际结果填写；未填写的版本不代表已验证。

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
| Android | Android Studio、Kotlin及相关编译插件、JDK、Gradle、AGP、compile/min/target SDK | 开发命令行 JDK 24.0.1；Gradle 9.4.1；AGP 9.2.1；Kotlin 2.2.10；KSP 2.3.12；compileSdk 37 / minSdk 26 / targetSdk 36（构建通过 2026-10-07） | 构建+单测通过；2026-10-09 正式模型真机识别通过 |
| Android 依赖 | CameraX、Room、tflite/LiteRT 与网络库 | CameraX 1.6.2；Room 2.8.5（KSP 2.3.12）；LiteRT 1.4.1（`org.tensorflow.lite` API）；Retrofit 3.0.0 + OkHttp 5.5.0；WorkManager 2.12.0；DataStore 1.2.1；kotlinx-serialization 1.11.0；Compose BOM 2026.09.00（见 android/gradle/libs.versions.toml） | 版本锁定待真机回归后冻结 |
| 真机 | 型号、Android 版本、处理器、内存 | 小米 13 Pro（Android 版本、处理器与内存待补） | 2026-10-09：正式模型 campus-gpu-v1 加载并识别键盘/鼠标/水杯，置信度 99.0–99.8%，单次耗时预处理 40–183ms、推理 10–29ms（非 P50/P95）；证据见 tests/evidence/2026-10-09-*.jpg |
| 后端 | Python、Flask、SQLAlchemy、PyMySQL、依赖与配置加载方式 | Windows Python 3.11.4、Linux Python 3.14.4；Flask 3.1.3；Flask-SQLAlchemy 3.1.1；SQLAlchemy 2.0.54；PyMySQL 1.2.3；python-dotenv 1.2.4；Werkzeug 3.1.9；pytest 9.1.1；独立.venv | 2026-10-08：两种环境各75项通过、3项SQLite参数下的MySQL专用用例跳过；真实MySQL、并发、HTTP入库/重试/冲突及服务重启持久性通过 |
| 云端推理 | LiteRT Python运行时、模型与标签哈希、CPU线程与推理并发 | 待填写 | 待验证 |
| 数据库 | MySQL 版本、字符集、时区与备份方式 | 本机隔离MySQL 8.0.25；云端MySQL 8.4.11；InnoDB、utf8mb4_bin、UTC会话、DATETIME(3)；每日备份保留七天 | 2026-10-08：四表SQL、种子、约束及受限运行账号已验证；备份和隔离恢复通过 |
| Web | 浏览器版本与支持范围 | 待填写 | 待验证 |
| 训练 | OS/WSL、Python、TensorFlow、Keras、依赖清单 | Windows 11 / Python 3.13.0 / TensorFlow 2.21.0 / Keras 3.12.1 / NumPy 2.1.3；WSL候选Ubuntu24.04+Python3.12 | 2026-10-07 CPU训练、保存、FP32导出、LiteRT加载通过；GPU待WSL安装验证 |
| 各训练 PC | PC 标识、GPU、显存、驱动、实际 GPU 可用状态 | 本机 i9-13900HX / RTX4060 Laptop 8188MiB / 驱动592.82 | 显卡硬件已检测；Windows TF仅CPU；其他PC未登记 |
| 云端 | Linux、Python、Gunicorn、Nginx、CPU、内存、磁盘余量 | Ubuntu 26.04 LTS x86_64；Python 3.14.4；Gunicorn 25.3.0；Nginx 1.28.3；2核、约4GB内存、42GiB磁盘余量 | 2026-10-08：systemd服务及每日备份启用；IP自签名HTTPS、Bearer保护和公网201/200/409通过；云端模型尚未加载 |

首日由组长汇总4台PC配置与GPU实际可用状态，各模块负责人提供版本、依赖锁定文件和复现命令。先验证小样本训练、模型转换和真机加载，再统一锁定依赖版本。新资料中的Python 3.11与TensorFlow 2.15仅为建议，不覆盖下方已实测工具链；其他PC与云端分别验证。各 PC 比较候选实验时使用相同环境和配置口径。实际 CPU/GPU 使用情况如实记录。

各模块提交构建配置、依赖清单和适用的锁定文件，补充复现命令；不提交本地环境目录或凭据。部署模板中的服务器账号和路径在 [部署说明](../deploy/README.md) 明示。

### 本机已知问题（开发机，2026-10-07）

- **系统 PATH 含有一个多余的双引号**（`E:\WEB\apache-tomcat-8.5.69\lib"`），导致 Gradle 单元测试 worker 的
  `-Djava.library.path` 参数被引号拆坏，报 `ClassNotFoundException: Files\Git\cmd;D:\node;C:\Program`。
  会话内用 `PATH=$(echo "$PATH" | tr -d '"')` 清洗后可正常构建；建议尽快在系统环境变量中修复该条目，
  否则 Android Studio 内运行单元测试也会遇到同样问题。
- Python 环境安装 TensorFlow 需用 Windows 专用包：`pip install tensorflow-intel`（2.18.0 验证可用，
  `pip install tensorflow` 在原生 Windows 无新版本 wheel）。

训练与云端服务使用独立Python环境。云端运行与手机相同的FP32 tflite，从一个Gunicorn worker和受控推理并发开始，记录实际内存和CPU；默认离线识别不依赖云端模型加载成功。模型更新后同步检查两端版本、哈希及预处理。

## 2026-10-07 模型工具链实测

Windows CPU依赖锁：`ml/requirements-windows-cpu.lock`。独立LiteRT版本2.2.0。
试验发布包 `smoke-20261007-export-v3`：FP32 8,939,036字节；20张合成fixture
在Keras/TFLite中Top-1一致，最大分数差2.03e-6。LiteRT同图重新加载验证通过。
合成fixture没有真实物品标签，其准确率不作正式成绩。

本机CPU、1线程、预热20次、测100次：纯推理P50约10.24ms/P95约20.63ms；
预处理加推理P50约17.42ms/P95约30.98ms。原始JSON位于
`experiments/reports/benchmarks/smoke-20261007-export-v3/`。
这些不是手机或腾讯云性能结果。

2026-10-07 20:53已通过管理员脚本成功启用WSL和VirtualMachinePlatform，日志保存在
`experiments/reports/environment/wsl-admin-install.log`；没有自动重启。
20:59安装程序返回0，实际安装WSL3.0.1.0、内核6.18.40.1-1。正常用户环境核验显示
尚无已注册的发行版，WSL2当前不能启动；系统组件刚启用，先重启再复核，不能据此认定BIOS虚拟化关闭。
记录见 `experiments/reports/environment/wsl-post-install-unsandboxed.json`；沙箱内的E_ACCESSDENIED另行保存，不能混作系统状态。
重启后运行 `wsl --install -d Ubuntu-24.04 --no-launch` 并核对 `wsl -l -v`，
然后创建Linux账号；首次账号密码只在本人终端输入。
安装、重启及首次账号步骤参照[Microsoft官方说明](https://learn.microsoft.com/en-us/windows/wsl/install)。
随后使用 `scripts/setup-ml-wsl.sh` 安装候选依赖和验证GPU，完成前保持待验证。

真实照片先导包 `pilot-cpu-tuned-v1`：386张训练、128张验证，公开验证准确率86.72%、
宏F1=0.8250；FP32 8,939,040字节。完整验证集Keras/LiteRT最大分数差8.35e-6，
20张真实交接照片的独立LiteRT重载分数差0。单线程20次预热/100次计时，
纯推理P50/P95=9.65/10.36ms，预处理加推理P50/P95=27.03/38.50ms。
这些是本机CPU实验；新版877张数据的后续实验使用独立版本并另行报告。
