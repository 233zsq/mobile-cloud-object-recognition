# 云端 API

状态：已实现健康检查、记录上传/UUID去重、纠错、分页查询、统计、类别查询和单图片CPU推理。字段兼容当前Android DTO，真机端到端验收仍需双方完成。

## 已实现：GET /api/health

返回200及JSON：`status: "ok"`、`version: "0.1.0"`，以及实际模型状态。未配置CPU进程时为 `model_loaded:false`、`model_version:null`、`model_status:"not_initialized"`；已校验的模型进程可用时为 true、实际模型版本和 `ready`；进程故障或身份不符时为 false、null 和 `unavailable`。version为服务版本，可通过APP_VERSION配置。此接口验证服务存活，不检查数据库；模型故障不改变200状态。允许传入 `?client=android`，当前忽略该查询参数。

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

调用前按 [数据库初始化说明](../../database/README.md) 建表、导入类别并登记模型。非空API_TOKEN启用Flask与Nginx两层Bearer认证，缺失或错误返回401；health公开可读，仅本地未设置口令时免认证。API响应为Cache-Control: no-store。令牌及证书信任方式见 [部署说明](../../deploy/README.md)。

## 接口总览（全部已实现）

| 方法与路径 | 输入或查询 | 预期行为 |
| --- | --- | --- |
| `POST /api/records` | UUID、客户端、来源device/cloud、模型版本、预测类别、分数、耗时、采集时间 | 校验并保存一次；相同UUID与内容返回已有记录；内容冲突不能覆盖 |
| `PATCH /api/records/{id}/label` | `corrected_id`、`revision`、`corrected_at` | 保留原预测；新修订更新人工标签；旧修订不能覆盖新标签 |
| `GET /api/records` | 时间范围、页码、类别、模型版本 | 分页返回记录和修正信息 |
| `GET /api/stats` | 起止时间、可选模型版本 | 返回总数、类别计数、耗时、低置信数量与生成时间 |
| `GET /api/categories` | 无 | 返回正式类别 ID 与显示名称 |
| `GET /api/health` | 无 | 返回服务和模型加载状态、版本；模型异常不阻断记录接口 |
| `POST /api/infer` | 单张照片、request_id、模型版本 | 用同版CPU模型返回预测、版本、哈希及阶段耗时；不自动入库 |

## 已实现：POST /api/infer

Content-Type为 `multipart/form-data`，必须且只能包含一个文件字段 `image` 和各一个文本字段 `request_id`、`model_version`。request_id须为带连字符UUID；model_version须与当前加载版本一致，目前为campus-evolve-v2、类别campus-10-v4，以health为准。沿用Bearer认证。
模型在独立Python 3.12工作进程启动时校验并加载，与手机使用同一份FP32 tflite、标签和预处理规则；Flask原环境不导入LiteRT或TensorFlow。

成功返回200，字段包含 `request_id`、`model_version`、`model_sha256`、`predicted_id`、`label_key`、`confidence`、`low_confidence`、10类 `scores`、`preprocess_ms`、`inference_ms`、`model_call_ms` 及 `server_ms`。成功响应request_id为客户端UUID（规范为小写）；X-Request-ID仍为服务端生成的追踪UUID，错误体沿用该服务端编号。
preprocess_ms覆盖工作进程内读取、解码和预处理，inference_ms只覆盖Interpreter推理，model_call_ms另包含同实例锁等待；server_ms覆盖Flask路由开始到响应字典构造完成，包括图片校验、IPC和工作进程处理。手机另测含网络和外部排队的总等待时间。

文件限制8MiB，整个HTTP请求限制10MiB，解码像素限制12,600,000；仅接受单帧JPEG、PNG、WebP，不信任扩展名或上传MIME。图片处理后删除。工作进程一次仅接收一张图片，额外请求返回忙碌，不排队；IPC超时15秒，Nginx既有限流继续生效。

| 场景 | 状态码 / 错误码 |
| --- | --- |
| 字段缺失、多余、重复或UUID错误 | 400 INVALID_INFER_REQUEST |
| 空图片、无法解码或图片损坏 | 400 INVALID_IMAGE |
| 请求模型版本不一致 | 409 MODEL_VERSION_MISMATCH |
| 图片文件或像素超限 | 413 IMAGE_TOO_LARGE |
| 总请求体超限 | 413 REQUEST_ENTITY_TOO_LARGE（Flask），超过Nginx限制时由代理直接拒绝 |
| 请求Content-Type错误 | 415 UNSUPPORTED_MEDIA_TYPE |
| 不支持的图片格式或动画 | 415 UNSUPPORTED_IMAGE |
| 模型未配置、进程不可用或身份/响应校验失败 | 503 MODEL_UNAVAILABLE |
| 已有图片正在处理 | 503 INFERENCE_BUSY |
| IPC超时 | 503 INFERENCE_TIMEOUT |
| 缺失或错误Bearer令牌、代理限流 | Nginx 401 / 429 |

推理接口不自动创建采集记录。用户采用结果后通过`/api/records`保存原UUID一次，`inference_source`为`device`或`cloud`；同图对比结果进入实验清单，不覆盖既有原预测。照片默认处理后释放，不自动加入训练数据。

## 已实现：PATCH /api/records/{id}/label

JSON必须且只能包含以下字段：

```json
{"corrected_id":3,"revision":1,"corrected_at":"2026-10-12T10:00:00.123+08:00"}
```

corrected_id是记录所属类别版本内0～9的整数；revision是1～2^63−1的整数，不接受布尔值、字符串或浮点数。时间规则与captured_at相同，规范为UTC毫秒；URL中的UUID规范为小写。

- 新revision大于已有revision：200，`{"updated":true,"record":{...}}`，通过条件UPDATE原子比较并更新，允许跳过离线期间未上传的中间修订。
- 相同revision、类别及规范化时间：200，updated=false，可安全补传。
- 旧revision或同revision的不同类别/时间：409 REVISION_CONFLICT，不覆盖。
- 原记录未上传：404 RECORD_NOT_FOUND；字段非法：400 INVALID_CORRECTION；类别不属于记录的类别版本：400 UNKNOWN_CATEGORY。
- 非JSON为415，损坏JSON为400，数据库故障为503。

原预测、分数、耗时、采集时间和上传指纹不改变。纠错后重试原POST仍返回200，且不会清空纠错。

## 已实现：GET /api/records 与 GET /api/stats

共享以下筛选，省略时查询全部已入库记录。时间依据captured_at；未知、重复或非法参数返回400 INVALID_QUERY。

| 参数 | 规则 |
| --- | --- |
| start、end | 带时区ISO-8601，最多3位小数；范围[start,end)，同时指定时start必须早于end |
| model_version | 已登记模型；未知为400 UNKNOWN_MODEL_VERSION |
| category_version | 已登记类别；未知为400 UNKNOWN_CATEGORY_VERSION；与模型同时指定必须一致 |
| category_id | 0～9整数 |
| category_basis | predicted（默认，按原预测筛选）或effective（修正类别优先，否则沿用原预测） |
| client_id | 带连字符UUID |
| inference_source | device或cloud |

URL中的`+08:00`需将加号编码为`%2B`，URLSearchParams会自动处理。

records另支持page（**从0开始**，兼容Android现有定义；默认0，最大1,000,000）与page_size（默认20，1～100）：

```json
{"records":[],"total":0,"page":0,"page_size":20,"pages":0,"filters":{"category_basis":"predicted"},"generated_at":"2026-10-12T02:00:00.000Z"}
```

按captured_at降序、record_id升序排序；超出页数返回空数组。记录字段与POST一致，包括纠错信息。分页期间新增记录可能改变页边界。

stats返回total_count、corrected_count（有人工标签的数量）、low_confidence_count、device_count、cloud_count、latency_ms（average/min/max）、categories、daily_counts、models、filters、generated_at及timezone=UTC。无记录时计数为0、耗时为null、趋势为空。

- categories按类别版本＋ID分别返回label_key、display_name、predicted_count（原预测）、corrected_count（仅人工标签）、effective_count（人工标签优先，未修正沿用原预测）；版本不混并，无记录类别为0。
- 低置信使用每条记录所属模型的登记阈值，confidence严格小于阈值；纠错不改变原置信度。
- daily_counts为按UTC日期的`[{"date":"2026-10-12","count":2}]`；models按模型版本返回数量。
- 耗时是记录中的预处理＋推理，不含HTTP网络等待；修正比例不能视为独立模型准确率。
- 数据库故障返回503，不以部分结果作为成功；health仍可用。

## 已实现：GET /api/categories

可指定model_version或category_version，两者同时指定须一致。默认选择INFERENCE_MODEL_VERSION对应的已登记类别，配置模型未登记时使用最近登记模型；只有类别时使用已登记版本。

返回category_version、categories（按ID排序的id/label_key/display_name/definition）、catalogs（以类别版本为键的全部清单）、models（model_version/category_version/low_confidence_threshold）。categories兼容Android的CategoriesResponse，额外字段用于解释历史记录。

## Web与联调

同域`/`提供统计页，`/assets/`提供静态资源；API使用Bearer请求头，不启用跨域访问。操作员输入现有口令，只保存在页面内存，断开或刷新后清除；不写入源码、URL或浏览器存储。每5秒刷新、失败保留上次数据并提示，支持筛选及翻页。见 [Web说明](../../web/README.md)。

接口契约已实现并验证，仍需Android负责人完成真实手机补传、纠错及新模型验收，由组长确认最终证据；不能将后端模拟请求记为真机通过。
