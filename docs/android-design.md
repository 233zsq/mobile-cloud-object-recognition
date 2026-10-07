# Android App 设计说明

负责人：Android 开发负责人（刘亮）。对应计划书 5.8「模型转换与端侧推理」与分工清单「刘亮：Android采集、识别与同步」。

## 技术栈与结构

Kotlin + Jetpack Compose（组内确认；计划书「Java」按泛指理解）、CameraX、LiteRT（原 TensorFlow Lite）、Room、Retrofit/OkHttp、WorkManager、DataStore。模块按仓库骨架分为 camera / inference / data / sync / ui 五层，`AppGraph` 手动装配（课程规模下不引入 DI 框架）。

```text
拍照 → PhotoStore（EXIF 直立化）→ ModelRepository/TfliteClassifier（中心裁剪→224缩放→归一化→推理）
     → RecordEntity 写入 Room（UUID 首次生成固定）→ SyncScheduler 触发上报
     → RecordUploader：POST /api/records、PATCH /api/records/{id}/label
```

## 关键设计约定

### 模型包加载（T04）
启动/重载时校验：输入 4 维批 1 正方形 3 通道 float32；输出 [1, N] 且 N = labels.txt 行数；
metadata.json 必须含 model_version；SHA-256（模型与标签）填写即强制比对；归一化取
`input.normalization`（mobilenet_v2_minus1_1 默认 / unit_0_1）。任何校验失败 → 停止识别并
显示中文原因，不产生伪结果。量化模型当前显式拒绝（契约要求另行适配输入输出编码）。

### 预处理
EXIF 由 PhotoStore 解码时统一应用（CameraX 写入 EXIF，BitmapFactory 不自动旋转，T02），
推理侧假设输入已是直立图；中心裁剪 → 双线性缩放到模型输入边长 → 按 metadata 预设归一化。
RGB 通道顺序；耗时分开计量：预处理（裁剪+缩放+归一化）与推理（interpreter.run）。

### UUID 与幂等（T07/T08）
recordId 在照片识别成功时生成（UUID v4），入库后永不变更；上报、补传、手动同步都用同一
UUID。首次保存的原始预测不可变。服务端按 UUID 去重（同 UUID 同内容返回已有记录）。

### 纠错与修订号（T10/T11）
纠错不覆盖原预测：`correctedIndex/correctedLabel/correctedAt` 独立字段；`revision` 从 0
开始每次纠错 +1，本地持久化后递增再 PATCH。服务端旧修订拒绝 → 显示冲突提示，记录保留待传。

### 同步状态机
```text
uploaded=0 ──POST 2xx──> uploaded=1
uploaded=1 且 correctionPending=0 ──纠错──> correctionPending=1 ──PATCH 2xx──> correctionPending=0
失败 → lastError 记录原因（展示），状态不变，等待下次触发
```
三条触发路径：新记录入库后；ConnectivityManager 网络恢复回调（T07）；记录页「立即同步」。
后台触发走 WorkManager（网络约束 + 指数退避 10s，最多 3 次重试后放行等待下次触发），
手动触发直接调用同一 RecordUploader（幂等，无并发风险：单设备串行上传）。

### 设置
baseURL / 访问令牌存 DataStore，改后即时生效（OkHttp 拦截器重写 URL，无需重装）；
client_id 首启生成固定；「测试连接」调用 GET /api/health。

## 已知边界（如实记录）

- LiteRT 1.4.1 固定 `org.tensorflow.lite.Interpreter` API；升级 2.x 需 Kotlin ≥2.4，暂缓。
- compileSdk 37（navigation 2.10.x 要求），targetSdk 保持 36。
- 占位模型为随机权重，仅验证链路；`scripts/make_placeholder_model.py` 生成，禁止用于准确率结论。
- 上传失败 409（UUID 内容冲突）会长期保持待传并显示错误，需人工介入——设计如此，不做静默覆盖。
- 云端推理 `POST /api/infer`（架构图中的主动云端识别）未接入 UI：按分工清单属于联调后扩展，
  网络层已具备接入条件（ApiService 增加方法即可）。

## 单元测试

- PreprocessMathTest：EXIF 角度映射、中心裁剪几何、归一化数值、形状解析。
- ModelValidatorTest：基线通过、标签数不符、量化拒绝、通道数、缺版本、空标签、metadata 宽容解析。
- RecordMapperTest：请求字段映射（含 inference_source=device）、修订号、ISO 时间、错误文案、pendingSync 状态机。
- CategoryCatalogTest：草案解析、未知标签回退、损坏 JSON 回退。
