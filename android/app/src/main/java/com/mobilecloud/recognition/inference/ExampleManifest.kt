package com.mobilecloud.recognition.inference

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 交接样例清单（models/examples/manifest.json，随发布包交付）。
 * 每项含样例 ID、图片文件、参考张量文件、期望分数与 Top-1，端云一致性自检使用。
 * 未知字段（来源署名等）忽略。
 */
@Serializable
data class ExampleSample(
    @SerialName("sample_id") val sampleId: String,
    val image: String,
    val tensor: String,
    @SerialName("tensor_sha256") val tensorSha256: String? = null,
    @SerialName("image_sha256") val imageSha256: String? = null,
    /** 模型在参考张量上的 golden 分数（10 类 softmax） */
    val scores: List<Double> = emptyList(),
    @SerialName("predicted_id") val predictedId: Int = -1,
    @SerialName("category_id") val categoryId: Int = -1,
) {
    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun parse(text: String): List<ExampleSample> =
            runCatching { json.decodeFromString<List<ExampleSample>>(text) }
                .getOrElse { throw IllegalArgumentException("样例清单解析失败：${it.message}") }
    }
}