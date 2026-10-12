# Android 客户端

负责人：Android 开发负责人（@fish123233）。

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

Windows 中文工作区的 AGP 路径检查已显式放行；若 JVM 测试报 `ClassNotFoundException`，
使用未占用的临时英文盘符运行同一工作区，例如 `subst R: "D:\项目路径\仓库"` 后执行
`R:\android\gradlew.bat -p R:\android :app:assembleDebug :app:testDebugUnitTest`。
用完执行 `subst R: /D` 取消映射，无须移动源码。2026-10-11 已用 JBR 21.0.10 完成 91 项单元检查。

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
| `app/src/main/assets/categories.json` | campus-10-v4 类别 ID/标签键/中文名，与 v2 模型同步 |

## 已实现功能（对应项目分工清单）

- CameraX 预览拍照、权限拒绝说明与重试、照片方向按 EXIF 统一处理（T01/T02）。
  **导入图片识别**：系统图片选择器（无需存储权限）→ 按字节复制进私有目录（保留 EXIF）→
  与拍照完全相同的识别链路；未授予相机权限时仍可用。
- 模型包（tflite+labels+metadata）加载校验：形状/标签数/SHA-256/版本，失败停止识别并提示（T04）。
- 预处理（契约 `rgb-letterbox-v1`：等比 half-pixel 双线性 + 灰色128居中补边 + 直送 0–255，
  归一化在模型内部）与推理在后台线程执行，显示类别、置信度、耗时、模型版本；
  低于阈值显示「需要确认」（F02）。
- Room 保存识别记录与同步状态；UUID 首次生成为止不变（F03/T06）。
- 记录页按模型版本筛选本机记录，默认全部；记录、待同步和已修正计数随筛选变化，
  单条记录显示真实模型版本。选项来自本机历史记录，新增版本无需改代码，筛选状态支持页面／进程恢复。
  「同步全部」和更多菜单中的「清空全部本地记录」仍作用于全库，清空确认使用全库数量。
  这只筛选历史，不切换识别模型；双端「观察手册」基调见 `docs/ui-style.md`。
- 采集页支持拍照／相册的本地、云端手动切换，默认本地。云端发送去除元数据、最长边不超过 2048 的 JPEG 副本，
  使用设置中的组内服务器和访问令牌；失败保留照片，可重试或手动转本地。记录和上报保存实际推理来源。
  云端先验证版本、完整模型哈希及分数，成功后沿用 Room／上报流程，推理接口本身不写记录。
  Room 1→2 显式迁移，旧记录补为本地来源并保留修正与同步状态。
- 记录页可**本地删除**单条记录或**「清空全部」**批量清理（含照片文件，均需二次确认）：
  删除只作用于本机，后端无删除接口，已入库记录在云端仍然保留，确认框按同步状态分别说明影响。
- 人工纠错：底部面板选类别，原预测保留、修订号递增、纠正时间记录（T10）。
- 上报 `POST /api/records` 与纠错 `PATCH /api/records/{id}/label`；失败保待传，
  WorkManager 网络约束+退避、网络恢复回调、记录页「立即同步」三条补传路径（T07/T08）。
- 服务器地址与令牌在设置页可改，即时生效；「测试连接」调 `GET /api/health`。

## 模型文件

模型二进制被根 `.gitignore` 忽略。当前选定发布包为 `models/releases/campus-evolve-v2/`：
`labels.txt` 与 `metadata.json` 可直接复制，`model.tflite` 从交付归档/组内共享存储领取，
三者必须同包（App 强制校验 SHA-256）。输入契约 `rgb-letterbox-v1` 由
`util/PreprocessMath.kt` 与 `inference/TfliteClassifier.kt` 实现，细节见
`app/src/main/assets/models/README.md`。
审批附录随本地交付包保留。Android 类别文件取 `shared/category-versions/campus-10-v4.json`，
旧基准及其 v2 类别文件保留。部署证据与待验收项见 `docs/campus-evolve-v2-deployment.md`。

占位模型（链路验证用，不得用于准确率结论，输入输出与契约一致）：

```bash
python scripts/make_placeholder_model.py   # 仓库根目录执行，需要 tensorflow
```

## 联调说明

- **组内云端已部署**：`https://49.232.195.47`（443现使用自动续期的可信IP证书，App已有系统CA信任，
  见 `res/xml/network_security_config.xml`）；`POST/PATCH` 需要
  `Authorization: Bearer <API_TOKEN>`，令牌在 App「我的 → 云端连接」填写（勿提交到仓库）。
- 默认占位地址 `http://localhost:8080`（与 `.env.example` 的 `API_BASE_URL` 一致）表示"未配置"，
  此时请求快速失败并保留待传记录。
- 局域网/自签环境联调：debug 构建信任设备上用户安装的 CA，可在手机上安装对应证书后使用 https；
  明文 http 联调在 base-config 中保留，后端全面 HTTPS 后收紧。
- 字段名提案与冻结项见 `docs/api/android-client-notes.md`；配置以原子快照读写（地址与令牌同源）。
