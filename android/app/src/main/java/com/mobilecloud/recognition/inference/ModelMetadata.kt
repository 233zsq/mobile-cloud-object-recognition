package com.mobilecloud.recognition.inference

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 模型包 metadata.json 的解析模型，字段定义与仓库根目录 models/metadata.template.json 一致。
 * 模型包由训练负责人按 docs/model-contract.md 交接。
 */
@Serializable
data class ModelMetadata(
    val status: String? = null,
    @SerialName("model_version") val modelVersion: String? = null,
    @SerialName("model_file") val modelFile: String = "model.tflite",
    val sha256: String? = null,
    @SerialName("labels_file") val labelsFile: String = "labels.txt",
    @SerialName("labels_sha256") val labelsSha256: String? = null,
    @SerialName("category_version") val categoryVersion: String? = null,
    @SerialName("data_version") val dataVersion: String? = null,
    @SerialName("experiment_id") val experimentId: String? = null,
    @SerialName("low_confidence_threshold") val lowConfidenceThreshold: Float? = null,
    val input: InputSpec = InputSpec(),
    val output: OutputSpec = OutputSpec(),
    @SerialName("created_at") val createdAt: String? = null,
) {
    @Serializable
    data class InputSpec(
        val shape: String? = null,
        val dtype: String? = null,
        @SerialName("color_order") val colorOrder: String? = null,
        val orientation: String? = null,
        val crop: String? = null,
        val resize: String? = null,
        val normalization: String? = null,
        val quantization: String? = null,
    )

    @Serializable
    data class OutputSpec(
        val shape: String? = null,
        val dtype: String? = null,
        val interpretation: String? = null,
        val quantization: String? = null,
    )

    companion object {
        val json: Json = Json { ignoreUnknownKeys = true }

        fun parse(text: String): ModelMetadata = runCatching { json.decodeFromString(serializer(), text) }
            .getOrElse { throw ModelLoadException("metadata.json 解析失败：${it.message}") }
    }
}
