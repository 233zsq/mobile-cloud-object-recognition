package com.mobilecloud.recognition.inference

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

/**
 * 模型包 metadata.json 的解析模型。字段与正式发布包
 * （models/releases/campus-gpu-v1/metadata.json）和 models/metadata.template.json 对齐；
 * 未知字段忽略，保证新版本模型包不会因新增字段而加载失败。
 *
 * 注意：`input.shape` / `output.shape` 在正式包中是 JSON 数组 `[1,224,224,3]`，
 * 早期占位包是字符串 `"1,224,224,3"`，两种形式都必须可解析。
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
        val version: String? = null,
        val shape: JsonElement? = null,
        val dtype: String? = null,
        @SerialName("pixel_range") val pixelRange: List<Int>? = null,
        @SerialName("color_order") val colorOrder: String? = null,
        val orientation: String? = null,
        val crop: String? = null,
        val resize: String? = null,
        val padding: String? = null,
        val normalization: String? = null,
        @SerialName("byte_order") val byteOrder: String? = null,
        val quantization: String? = null,
    ) {
        val shapeArray: IntArray? get() = shape.toShapeArray()
    }

    @Serializable
    data class OutputSpec(
        val shape: JsonElement? = null,
        val dtype: String? = null,
        val interpretation: String? = null,
        val quantization: String? = null,
    ) {
        val shapeArray: IntArray? get() = shape.toShapeArray()
    }

    companion object {
        val json: Json = Json { ignoreUnknownKeys = true }

        fun parse(text: String): ModelMetadata = runCatching { json.decodeFromString(serializer(), text) }
            .getOrElse { throw ModelLoadException("metadata.json 解析失败：${it.message}") }
    }
}

/** 形状字段兼容 JSON 数组与逗号/×分隔字符串两种写法 */
fun JsonElement?.toShapeArray(): IntArray? = when (this) {
    null, is JsonNull -> null
    is JsonArray -> mapNotNull { (it as? JsonPrimitive)?.content?.trim()?.toIntOrNull() }
        .takeIf { it.isNotEmpty() }
        ?.toIntArray()
    is JsonPrimitive -> content
        .split(',', 'x', 'X', '×')
        .mapNotNull { it.trim().toIntOrNull() }
        .takeIf { it.isNotEmpty() }
        ?.toIntArray()
    else -> null
}