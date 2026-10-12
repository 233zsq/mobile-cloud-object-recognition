package com.mobilecloud.recognition.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 已联调的请求/响应契约，字段名与现有云端接口保持一致。
 * 变更时同步修改 RecordMapper 与 docs/api/android-client-notes.md。
 */
@Serializable
data class RecordUploadRequest(
    /** 记录 UUID，重试与补传保持不变 */
    @SerialName("record_id") val recordId: String,
    @SerialName("client_id") val clientId: String,
    /** 识别来源：device（端侧）/ cloud（云端） */
    @SerialName("inference_source") val inferenceSource: String,
    @SerialName("model_version") val modelVersion: String,
    /** 原预测类别 ID（=模型输出索引） */
    @SerialName("predicted_id") val predictedId: Int,
    /** 置信度，0 到 1 */
    @SerialName("confidence") val confidence: Float,
    /** 预处理+推理耗时（毫秒） */
    @SerialName("latency_ms") val latencyMs: Long,
    /** 采集时间，ISO-8601 含时区 */
    @SerialName("captured_at") val capturedAt: String,
)

@Serializable
data class CorrectionRequest(
    @SerialName("corrected_id") val correctedId: Int,
    @SerialName("revision") val revision: Int,
    @SerialName("corrected_at") val correctedAt: String,
)

@Serializable
data class HealthResponse(
    val status: String? = null,
    @SerialName("model_loaded") val modelLoaded: Boolean? = null,
    val version: String? = null,
)

@Serializable
data class CategoriesResponse(
    val categories: List<CategoryDto> = emptyList(),
)

@Serializable
data class CategoryDto(
    val id: Int = -1,
    @SerialName("label_key") val labelKey: String = "",
    @SerialName("display_name") val displayName: String = "",
)

@Serializable
data class InferResponse(
    @SerialName("request_id") val requestId: String,
    @SerialName("model_version") val modelVersion: String,
    @SerialName("model_sha256") val modelSha256: String,
    @SerialName("predicted_id") val predictedId: Int,
    @SerialName("label_key") val labelKey: String,
    val confidence: Float,
    val scores: List<Float>,
    @SerialName("preprocess_ms") val preprocessMs: Double,
    @SerialName("inference_ms") val inferenceMs: Double,
    @SerialName("low_confidence") val lowConfidence: Boolean? = null,
)

@Serializable
data class CloudModelsResponse(
    @SerialName("default_model_version") val defaultModelVersion: String,
    val models: List<CloudModelOption>,
)

@Serializable
data class CloudModelOption(
    @SerialName("model_version") val version: String,
    @SerialName("model_sha256") val sha256: String,
    @SerialName("category_version") val categoryVersion: String,
    @SerialName("labels_sha256") val labelsSha256: String,
    @SerialName("display_name") val displayName: String,
    val description: String,
    val status: String,
    val labels: List<String>,
    @SerialName("low_confidence_threshold") val threshold: Float,
    val available: Boolean,
)
