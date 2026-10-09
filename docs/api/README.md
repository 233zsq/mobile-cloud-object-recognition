# 云端 API 草案

状态：已实现健康检查与记录上传/UUID去重，其余业务接口仍是待冻结草案。当前记录字段沿用Android功能分支已有提案，真实客户端联调尚待完成。数据与云端负责人维护，Android开发负责人和组长共同确认联调口径。

## 已实现：GET /api/health

返回200及JSON：`status: "ok"`、`version: "0.1.0"`、`model_loaded: false`、`model_version: null`、`model_status: "not_initialized"`。version为服务版本，可通过APP_VERSION配置。此接口仅验证服务存活，尚未检查数据库或加载模型；允许传入 `?client=android`，当前忽略该查询参数。

所有响应包含服务端生成的 `X-Request-ID`。错误响应为 `{"error":{"code":"NOT_FOUND","message":"..."},"request_id":"UUID"}`；保留实际HTTP状态码。未知路径为404、错误方法为405、读取超限请求体为413、未预期异常为500。启动和配置说明见 [backend/README.md](../../backend/README.md)。

## 已实现：POST /api/records

Content-Type为 `application/json`，请求体必须包含且只包含以下8个字段：

```json
{
  "record_id": "550e8400-e29b-41d4-a716-446655440000",
  "client_id": "9f1c3a20-7b52-4a1e-8a3f-2f4d5e6a7b8c",
  "inference_source": "device",
  "model_version": "expanded-cpu-v1",
  "predicted_id": 0,
  "confidence": 0.874,
  "latency_ms": 123,
  "captured_at": "2026-10-08T16:30:00.123+08:00"
}
```

| 字段 | 校验规则 |
| --- | --- |
| `record_id`、`client_id` | 带连字符的UUID，大小写统一为小写 |
| `inference_source` | device或cloud |
| `model_version` | 已登记版本；1至64位字母、数字、点、下划线、连字符，以字母或数字开头 |
| `predicted_id` | 0至9整数，属于模型对应类别版本；不接受布尔值或浮点数 |
| `confidence` | 0至1有限数值，不接受布尔值、NaN或Infinity |
| `latency_ms` | 预处理加推理耗时，非负64位整数，不含网络等待 |
| `captured_at` | 带时区的ISO-8601时间，以T分隔；最多3位小数，接受Z或±HH:MM；转为UTC毫秒入库 |

成功响应：`{"created":true,"record":{...}}`。record包含原始上传字段，并附加 `category_version`、`corrected_id`、`corrected_at`、`revision` 和 `created_at`；返回时间统一为UTC，例如 `2026-10-08T08:30:00.123Z`。新记录的纠错字段为null，revision为0。

| 场景 | 状态码与行为 |
| --- | --- |
| 新UUID | 201，created=true，保存一条记录 |
| 相同UUID、相同规范化内容 | 200，created=false，返回已有记录，不增加数量 |
| 相同UUID、不同原始内容 | 409 RECORD_CONFLICT，不覆盖原记录 |
| 非对象、缺字段、多余字段或非法值 | 400 INVALID_RECORD；损坏JSON为400 BAD_REQUEST |
| 未登记模型 | 400 UNKNOWN_MODEL_VERSION |
| 类别不属于模型对应类别版本 | 400 UNKNOWN_CATEGORY |
| Content-Type错误 | 415 UNSUPPORTED_MEDIA_TYPE |
| 数据库无法连接、表未初始化或数据库写入失败 | 503 DATABASE_UNAVAILABLE，可稍后使用相同UUID重试 |

去重覆盖全部8个原始字段。UUID大小写、同一时刻的不同时区表示及数值1/1.0会规范化；采集时间、置信度等实质内容变化会冲突。不同UUID分别计数，即使其他字段相同。数据库UUID主键约束处理并发竞争；事务失败回滚后读取已提交记录，再判断重复或冲突。后续人工纠错字段不参与原始上传去重，重试不会清空人工标签。

调用前按 [数据库初始化说明](../../database/README.md) 建表、导入类别并登记模型。Flask自身尚未实现Bearer认证，本地直接调用Gunicorn时API_TOKEN不限制访问。当前公网部署由Nginx检查 `Authorization: Bearer <API_TOKEN>`，缺失或错误返回401；令牌位置、IP地址和自签名证书信任方式见 [部署说明](../../deploy/README.md)。

## 接口总览（除health及POST records外仍待实现）

| 方法与路径 | 输入或查询 | 预期行为 |
| --- | --- | --- |
| `POST /api/records` | UUID、客户端、来源device/cloud、模型版本、预测类别、分数、耗时、采集时间 | 校验并保存一次；相同UUID与内容返回已有记录；内容冲突不能覆盖 |
| `PATCH /api/records/{id}/label` | `corrected_id`、`revision`、`corrected_at` | 保留原预测；新修订更新人工标签；旧修订不能覆盖新标签 |
| `GET /api/records` | 时间范围、页码、类别、模型版本 | 分页返回记录和修正信息 |
| `GET /api/stats` | 起止时间、可选模型版本 | 返回总数、类别计数、耗时、低置信数量与生成时间 |
| `GET /api/categories` | 无 | 返回正式类别 ID 与显示名称 |
| `GET /api/health` | 无 | 返回服务和模型加载状态、版本；模型异常不阻断记录接口 |
| `POST /api/infer` | 单张照片、request_id、模型版本 | 用同版CPU模型返回预测、版本、哈希及阶段耗时；不自动入库 |

## 云端单图片推理

计划由Flask提供`multipart/form-data`接口，字段为`image`、`request_id`和`model_version`。模型在启动时校验并加载，与手机使用同一份FP32 tflite、标签和预处理规则。

响应字段计划包含`request_id`、`model_version`、`model_sha256`、`predicted_id`、`confidence`、`preprocess_ms`、`inference_ms`及`server_ms`。`server_ms`表示处理程序内的总处理时间；手机另测请求发起至收到完整响应的总等待时间，覆盖网络和外部排队，不能把两者混为一项。

接口配置文件大小、解码检查、超时和受控并发；模型未就绪、格式错误、超限、服务忙碌时返回统一错误。确切限制与状态码在联调前冻结。

推理接口不自动创建采集记录。用户采用结果后通过`/api/records`保存原UUID一次，`inference_source`为`device`或`cloud`；同图对比结果进入实验清单，不覆盖既有原预测。照片默认处理后释放，不自动加入训练数据。

## 联调前需冻结

- 请求/响应 JSON 字段名称、类型、必填规则和示例，模型标识使用版本名还是数据库 ID。
- HTTP 状态码、统一错误结构、UUID 内容冲突及纠错冲突的返回行为。
- 时间格式、时区、毫秒精度，分页起点、页大小上限与默认时间范围。
- 认证方式、本地和部署地址、Web 认证交互与跨域/反向代理配置。
- 统计口径：原预测与人工修正分别展示，低置信阈值和模型版本的对应规则。
- 云端照片字段、文件限制、推理忙碌与超时状态、模型哈希、阶段计时边界及`inference_source`规则。

原预测首次入库后保持不变，重试使用同一UUID；不能把重复提交当成覆盖操作。修订号在手机本地保存并递增，后端纠错接口需原子地比较修订号后再更新。当前health及POST records可调用；GET records、PATCH label、stats、categories和infer尚未实现。
