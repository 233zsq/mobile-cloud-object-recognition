# Android 客户端

负责人：Android 开发负责人（刘亮）。

**当前状态：App 首版可构建。** 采用 Kotlin + Jetpack Compose（计划书已同步切换为 Kotlin），
CameraX 采集、LiteRT 端侧推理、Room 本地记录、Retrofit 上报与补传均已实现，
依赖版本见 `docs/environment.md`。

## 构建

```bash
cd android
./gradlew assembleDebug          # 产出 app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest      # JVM 单元测试
```

要求：JDK 17+（本机验证 JDK 24）、Android SDK Platform 37。开发机路径写入被忽略的
`local.properties`（`sdk.dir=...`）。依赖版本以 `gradle/libs.versions.toml` 为准，
真机验证后登记 `docs/environment.md`。

安装：`adb install -r app/build/outputs/apk/debug/app-debug.apk` 或直接传 APK 安装。

## 目录与职责

Kotlin 源码按 Android 约定放在 `java/` 目录下（`.kt` 文件），包名为 `com.mobilecloud.recognition`。

| 目录 | 用途 |
| --- | --- |
| `app/src/main/java/com/mobilecloud/recognition/camera/` | 拍照文件管理、EXIF 方向 |
| `app/src/main/java/com/mobilecloud/recognition/inference/` | 模型包加载校验、预处理与后台推理 |
| `app/src/main/java/com/mobilecloud/recognition/data/` | Room 记录、设置存储、类别清单 |
| `app/src/main/java/com/mobilecloud/recognition/sync/` | 接口访问、上传 Worker、补传与纠错修订号 |
| `app/src/main/java/com/mobilecloud/recognition/ui/` | 采集、记录、设置三屏（Compose） |
| `app/src/main/assets/models/` | 正式模型、标签与 metadata 打包位置（见目录内 README） |
| `app/src/main/assets/categories.json` | 类别 ID/标签键/中文名（草案；冻结后替换） |

## 已实现功能（对应项目分工清单）

- CameraX 预览拍照、权限拒绝说明与重试、照片方向按 EXIF 统一处理（T01/T02）。
- 模型包（tflite+labels+metadata）加载校验：形状/标签数/SHA-256/版本，失败停止识别并提示（T04）。
- 预处理（中心裁剪→缩放→归一化）与推理在后台线程执行，显示类别、置信度、耗时、模型版本；
  低于阈值显示「需要确认」（F02）。
- Room 保存识别记录与同步状态；UUID 首次生成为止不变（F03/T06）。
- 人工纠错：底部面板选类别，原预测保留、修订号递增、纠正时间记录（T10）。
- 上报 `POST /api/records` 与纠错 `PATCH /api/records/{id}/label`；失败保待传，
  WorkManager 网络约束+退避、网络恢复回调、记录页「立即同步」三条补传路径（T07/T08）。
- 服务器地址与令牌在设置页可改，即时生效；「测试连接」调 `GET /api/health`。

## 模型文件

模型二进制被根 `.gitignore` 忽略。正式发布包为 `models/releases/campus-gpu-v1/`：
`labels.txt` 与 `metadata.json` 可直接复制，`model.tflite` 从交付归档/组内共享存储领取，
三者必须同包（App 强制校验 SHA-256）。输入契约 `rgb-letterbox-v1` 由
`util/PreprocessMath.kt` 与 `inference/TfliteClassifier.kt` 实现，细节见
`app/src/main/assets/models/README.md`。

占位模型（链路验证用，不得用于准确率结论，输入输出与契约一致）：

```bash
python scripts/make_placeholder_model.py   # 仓库根目录执行，需要 tensorflow
```

## 联调说明

- **组内云端已部署**：`https://49.232.195.47`（IP 自签名证书，`deploy/certs/server.crt`
  已内置信任，见 `res/xml/network_security_config.xml`）；`POST/PATCH` 需要
  `Authorization: Bearer <API_TOKEN>`，令牌在 App「设置」页填写（服务器端配置持有真实值，勿提交到仓库）。
- 默认占位地址 `http://localhost:8080`（与 `.env.example` 的 `API_BASE_URL` 一致）表示"未配置"，
  此时请求快速失败并保留待传记录。
- 局域网/自签环境联调：debug 构建信任设备上用户安装的 CA，可在手机上安装对应证书后使用 https；
  明文 http 联调在 base-config 中保留，后端全面 HTTPS 后收紧。
- 字段名提案与冻结项见 `docs/api/android-client-notes.md`；配置以原子快照读写（地址与令牌同源）。
