# Android 端接口对接笔记（联调对齐用）

维护：Android 开发负责人。接口草案见同目录 `README.md`；本文件记录 Android 端已实现的
字段提案，供联调前冻结时逐项确认。**以下字段名尚未冻结，后端实现时应以此文为对齐起点。**

## POST /api/records 请求体提案

```json
{
  "record_id": "550e8400-e29b-41d4-a716-446655440000",
  "client_id": "9f1c3a20-7b52-4a1e-8a3f-2f4d5e6a7b8c",
  "inference_source": "device",
  "model_version": "placeholder-random-v0",
  "predicted_id": 5,
  "confidence": 0.874,
  "latency_ms": 123,
  "captured_at": "2026-10-07T18:30:00.000+08:00"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| record_id | string (UUID) | 手机端生成后永不变更；重试/补传同值（T07/T08） |
| client_id | string (UUID) | App 首启生成并固定，区分设备 |
| inference_source | string | `device` / `cloud`；App 端侧识别恒为 `device` |
| model_version | string | metadata.json 的 model_version |
| predicted_id | int | 类别 ID，= 模型输出索引（契约：二者一致） |
| confidence | float | 0 到 1，原始 float32 输出 |
| latency_ms | int | 预处理+推理耗时（毫秒），不含拍照与联网 |
| captured_at | string | ISO-8601 含毫秒与时区偏移 |

## PATCH /api/records/{id}/label 请求体提案

```json
{ "corrected_id": 3, "revision": 1, "corrected_at": "2026-10-07T18:31:10.000+08:00" }
```

- `revision` 从 0 开始，每次纠错 +1；手机本地持久化后递增。
- Android 端预期：2xx = 已按最新修订生效；409/422 = 有更新修订，旧请求不能覆盖（T11）。

## Android 端的 HTTP 语义假设（需确认）

| 场景 | Android 端处理 | 假设的服务端行为 |
| --- | --- | --- |
| 新 UUID | 标记已同步 | 2xx |
| 相同 UUID+相同内容重复提交 | 视为成功，标记已同步 | 2xx（返回已有记录） |
| 相同 UUID+不同内容 | 保留待传并显示冲突提示 | 409 |
| 字段校验失败 | 显示错误、保留待传 | 400 |
| 纠错修订过期 | 显示冲突提示、保留待传 | 409/422 |

- Android 不解析响应体内容（除 health/categories），状态码足够驱动本地状态机。
- 上报失败不丢弃、不删除记录；「立即同步」手动触发与后台自动补传使用同一执行器，天然幂等。

## 未冻结项与建议

1. **字段名**：上文 snake_case 提案如后端用其他命名，改 `data/remote/Dtos.kt` 的 `@SerialName` 即可，一处集中。
2. **时间格式**：App 发送 ISO-8601 偏移格式；如后端要求 epoch 毫秒，只需改 `RecordMapper.isoTime`。
3. **认证**：设置页可配置 Bearer Token（请求头 `Authorization`）；如改为 query 参数或签名，需同步调整拦截器。
4. **分页/时间范围**：App 预留了 `GET /api/records`（分页）与 `GET /api/categories` 定义，当前未用于 UI。
5. **错误结构**：后端统一错误 JSON 出来后，App 可增强错误展示（当前仅用状态码生成中文说明）。

## 联调前 Android 需要后端提供

- 服务地址（公网或与手机同网段）与是否启用 HTTPS。
- 令牌值与传递方式（或确认首版免认证）。
- 一条真实入库样例（`POST /api/records` 的成功响应码），用于对齐 T06/T08。
