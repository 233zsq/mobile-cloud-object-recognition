package com.mobilecloud.recognition.inference

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/**
 * 端云一致性报告构造（纯函数，便于单测）。
 * 字段与 scripts/make-handover-report.py 生成的模板一致；input_contract 必须原样嵌入
 * metadata.json 的 input 段（`python -m recognition verify` 逐字段比对）。
 */
object ConsistencyReport {

    const val MODE_REFERENCE_TENSOR = "reference_tensor"
    const val MODE_IMAGE_CHAIN = "image_chain"

    /** run_id 必须匹配 `recognition.common.safe_name`：仅字母、数字、下划线、连字符 */
    val SAFE_RUN_ID = Regex("[A-Za-z0-9_-]+")

    /**
     * 每份报告使用不同 run_id（交接约定）：同一 run_id 提交两种模式时，
     * 校验器会在第二份报告报 "Consistency evidence exists"。
     */
    fun runIdFor(base: String, mode: String): String = "$base-$mode"

    data class SampleReport(
        val sampleId: String,
        val scores: FloatArray,
        /** image_chain 模式必填：相对报告文件所在目录的张量文件名 */
        val tensorFile: String? = null,
        /** reference_tensor 模式必填：实际喂入字节的 SHA-256 */
        val tensorSha256: String? = null,
    ) {
        // FloatArray 的 equals/hashCode 需显式覆写，避免误用引用比较
        override fun equals(other: Any?): Boolean =
            other is SampleReport && sampleId == other.sampleId && scores.contentEquals(other.scores) &&
                tensorFile == other.tensorFile && tensorSha256 == other.tensorSha256

        override fun hashCode(): Int =
            ((sampleId.hashCode() * 31 + scores.contentHashCode()) * 31 + (tensorFile?.hashCode() ?: 0)) * 31 +
                (tensorSha256?.hashCode() ?: 0)
    }

    fun build(
        mode: String,
        runId: String,
        device: String,
        runtime: String,
        modelSha256: String,
        labelsSha256: String,
        inputContract: JsonElement,
        samples: List<SampleReport>,
    ): JsonObject {
        require(mode == MODE_REFERENCE_TENSOR || mode == MODE_IMAGE_CHAIN) { "mode 非法：$mode" }
        return buildJsonObject {
            put("run_id", runId)
            put("mode", mode)
            put("device", device)
            put("runtime", runtime)
            put("model_sha256", modelSha256)
            put("labels_sha256", labelsSha256)
            put("input_contract", inputContract)
            putJsonArray("samples") {
                samples.forEach { sample ->
                    addJsonObject {
                        put("sample_id", sample.sampleId)
                        putJsonArray("scores") { sample.scores.forEach { add(it) } }
                        sample.tensorFile?.let { put("tensor_file", it) }
                        sample.tensorSha256?.let { put("tensor_sha256", it) }
                    }
                }
            }
        }
    }

    /** 本地自评：与校验器同一口径（Top-1 一致、分数差 ≤0.001，图片模式另加输入像素差 ≤0.001） */
    data class LocalVerdict(
        val top1Same: Boolean,
        val maxScoreDiff: Double,
        val maxInputDiff: Double?,
        val passed: Boolean,
    )

    const val MAX_DIFF = 0.001

    fun evaluate(
        scores: FloatArray,
        goldenScores: List<Double>,
        goldenTop1: Int,
        inputDiff: Double?,
    ): LocalVerdict {
        val top1 = scores.indices.maxByOrNull { scores[it] } ?: -1
        val scoreDiff = if (goldenScores.size == scores.size) {
            scores.indices.maxOf { kotlin.math.abs(scores[it] - goldenScores[it].toFloat()).toDouble() }
        } else {
            Double.POSITIVE_INFINITY
        }
        val top1Same = top1 == goldenTop1
        val passed = top1Same && scoreDiff <= MAX_DIFF && (inputDiff == null || inputDiff <= MAX_DIFF)
        return LocalVerdict(top1Same, scoreDiff, inputDiff, passed)
    }

    /** 逐 float 比较两个契约张量字节流的最大绝对差（little-endian float32） */
    fun maxFloatDiff(a: ByteArray, b: ByteArray): Double {
        require(a.size == b.size) { "张量字节数不同：${a.size} vs ${b.size}" }
        val fa = java.nio.ByteBuffer.wrap(a).order(java.nio.ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        val fb = java.nio.ByteBuffer.wrap(b).order(java.nio.ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        var maxDiff = 0.0
        for (i in 0 until fa.capacity()) {
            val diff = kotlin.math.abs(fa.get(i) - fb.get(i)).toDouble()
            if (diff > maxDiff) maxDiff = diff
        }
        return maxDiff
    }

    /** 契约输入必须落在 0–255（重复归一化会被此检查与参考张量对照共同发现） */
    fun floatRange(bytes: ByteArray): Pair<Float, Float> {
        val f = java.nio.ByteBuffer.wrap(bytes).order(java.nio.ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        var min = Float.MAX_VALUE
        var max = -Float.MAX_VALUE
        for (i in 0 until f.capacity()) {
            val v = f.get(i)
            if (v < min) min = v
            if (v > max) max = v
        }
        return min to max
    }

    private fun kotlinx.serialization.json.JsonArrayBuilder.add(value: Float) = add(JsonPrimitive(value))
}