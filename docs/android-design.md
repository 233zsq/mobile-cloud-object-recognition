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
启动/重载时校验：输入 4 维批 1 正方形 3 通道 float32；输出 `[1, N]` 且 N = labels.txt 行数；
metadata.json 必须含 model_version；SHA-256（模型与标签）填写即强制比对；
`input.pixel_range` 必须为 `[0,255]`；归一化约定必须可解析；metadata 声明的
`input/output.shape` 必须与实际张量一致。任何校验失败 → 停止识别并显示中文原因，
不产生伪结果。量化模型当前显式拒绝（契约要求另行适配输入输出编码）。

### 预处理（契约 rgb-letterbox-v1，与云端/PC 参考实现逐字一致）
EXIF 由 PhotoStore 解码时统一应用（CameraX 写入 EXIF，BitmapFactory 不自动旋转，T02），
透明图片先在灰色(128)背景合成；推理路径以**原始分辨率**解码（不采样，避免改变插值结果），
缩略图等展示用途才采样。随后按契约 `docs/ml-handover.md`：

1. `scale = 224 / max(宽, 高)`，内框宽高 `floor(原尺寸 × scale + 0.5)`（round half up）；
2. 双线性、half-pixel 坐标（`source_x = (target_x + 0.5) × 源宽 / 内框宽 − 0.5`），
   不额外抗锯齿；**四邻域加权结果保留 float32 直接写入输入缓冲，不取整为 uint8**；
3. 灰色 128 居中补边至 224×224，奇数余量位于右/下，不裁剪；
4. 输入 `[1,224,224,3]` RGB float32、像素 0–255、little-endian 连续 NHWC（602112 字节）；
5. **归一化 `x/127.5−1` 在模型内部完成，端侧恒等直送**——重复归一化会被参考张量对照
   （`shared/device-results/`）检出，`NormalizationPreset.IDENTITY` 为契约路径，
   旧包的客户端归一化仅作兼容保留。

耗时分开计量：`preprocessMs` 覆盖 letterbox 缩放到输入缓冲就绪（含像素编码），
`inferenceMs` 只覆盖 `interpreter.run`。

### UUID 与幂等（T07/T08）
recordId 在照片识别成功时生成（UUID v4），入库后永不变更；上报、补传、手动同步都用同一
UUID。首次保存的原始预测不可变。服务端按 UUID 去重（同 UUID 同内容返回已有记录）。

### 纠错与修订号（T10/T11）
纠错不覆盖原预测：`correctedIndex/correctedLabel/correctedAt` 独立字段；`revision` 从 0
开始每次纠错 +1，本地持久化后递增再 PATCH。PATCH 成功仅在本地 revision 仍等于已发送
revision 时清除待同步标志，防止在途请求掩盖更新的修订（PR 审查修复项）。服务端旧修订
拒绝 → 显示冲突提示，记录保留待传。

### 同步状态机
```text
uploaded=0 ──POST 2xx──> uploaded=1
uploaded=1 且 correctionPending=0 ──纠错──> correctionPending=1 ──PATCH 2xx──> correctionPending=0
失败 → lastError 记录原因（展示），状态不变，等待下次触发
```
三条触发路径：新记录入库后；ConnectivityManager 网络恢复回调（T07）；记录页「立即同步」。
后台触发走 WorkManager（网络约束 + 指数退避 10s，最多 3 次重试后放行等待下次触发），
手动触发直接调用同一 RecordUploader（幂等，无并发风险：单设备串行上传）。

### 并发与资源约束
- **模型重载与推理共用同一把锁**：`classify` 全程持锁，`reload()` 必须等待在途推理结束，
  避免 `bundle.close()` 释放在用的 Interpreter（原生资源访问崩溃，PR 审查修复项）。
- 相机选择器先探测 `hasCamera`：无后置相机回退前置，均无则明确提示而不崩溃；绑定失败
  经 `runCatching` 转为采集页错误提示。
- 设置页保存前校验服务器地址格式，无效输入不写入持久化配置（否则重启后回退默认地址，
  上报与补传持续失败）。
- **配置以单个 `ServerConfig` 快照读写**：DataStore 一次事务写入地址与令牌，请求层用
  `AtomicReference` 原子替换，拦截器每个请求只读取一次快照（`RequestRewriter.plan`），
  避免并发切换时出现「A 的地址 + B 的令牌」交叉组合。
- 显式端口必须落在 `1..65535`，超出范围视为无效地址并在保存前拒绝。
- 透明图灰底合成使用与 Python 参考实现（PIL `alpha_composite`）一致的四舍五入
  `(v*a + bg*(255-a) + 127)/255`；截断会在半透明像素上产生 1 的偏差（已实测：截断 1 → 四舍五入 0）。

### 传输安全（TLS）
- 后端为 IP 自签名证书（`deploy/certs/server.crt`，CN/SAN `49.232.195.47`，有效期至
  2027-01-06）。`res/xml/network_security_config.xml` 的 domain-config **显式信任该公钥证书**，
  不依赖设备安装；服务器换证或换 IP 时同步更新该文件与 `deploy/certs/server.crt`。
- base-config 默认信任系统 CA；联调期保留明文 http 供局域网使用，后端全面 HTTPS 后收紧。
- debug 构建额外信任设备上用户安装的 CA（`debug-overrides`），便于局域网/自签环境联调；
  release 构建不生效。

### 类别清单
`assets/categories.json` 为 `shared/categories.json`（冻结版 campus-10-v2，2026-10-07）的
仓库内副本，类别 ID/标签键/中文名与模型输出索引一致；冻结清单变更时同步更新此副本。

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
