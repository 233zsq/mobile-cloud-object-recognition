package com.mobilecloud.recognition.inference

import com.mobilecloud.recognition.data.remote.ApiService
import com.mobilecloud.recognition.data.remote.InferResponse
import com.mobilecloud.recognition.data.remote.CloudModelsResponse
import com.mobilecloud.recognition.data.remote.CloudModelOption
import java.io.File
import java.util.UUID
import kotlin.math.abs
import kotlin.math.roundToLong
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody

/** Identity and scores must match the bundled contract before a result can be adopted. */
data class CloudModelContract(val version: String, val sha256: String, val labels: List<String>, val threshold: Float,
    val scopePolicy: ScopePolicy? = null) {
    fun validate(response: InferResponse, requestId: String): Prediction {
        require(response.requestId == requestId) { "云端响应编号不匹配，请重试" }
        require(response.modelVersion == version && response.modelSha256 == sha256) { "端云模型版本或哈希不一致，请联系管理员" }
        val scores = response.scores
        require(labels.size == 10 && scores.size == 10 && scores.all { it.isFinite() && it in 0f..1f } && abs(scores.sum() - 1f) <= .0001f) { "云端分数无效" }
        val index = scores.indices.maxBy { scores[it] }
        require(response.predictedId == index && response.labelKey == labels[index] && response.confidence == scores[index]) { "云端类别与分数不一致" }
        require(listOf(response.preprocessMs, response.inferenceMs).all { it.isFinite() && it >= 0 && it < 60_000 }) { "云端耗时无效" }
        require(response.lowConfidence == (response.confidence < threshold)) { "云端阈值与选定模型不一致" }
        val scope = if (scopePolicy == null || response.scopeDecision == null) {
            ScopeDecision(ScopeVerdict.UNAVAILABLE, null, null, "云端未提供可核验的范围判断，请人工确认")
        } else {
            val remote = response.scopeDecision
            val expected = ScopePolicyState(scopePolicy, scopePolicy.declaredSha256).evaluate(scores, remote.knownness)
            require(remote.policyVersion == expected.policyVersion && remote.policySha256 == expected.policySha256
                && remote.status == expected.verdict.name.lowercase(java.util.Locale.ROOT)
                && remote.needsConfirmation == expected.needsConfirmation) { "云端范围判断与模型规则不一致" }
            expected
        }
        return Prediction(index, response.confidence, response.labelKey,
            response.preprocessMs.roundToLong(), response.inferenceMs.roundToLong(),
            (response.preprocessMs + response.inferenceMs).roundToLong(), response.modelVersion, scores = scores.toList(), scopeDecision = scope)
    }
}

/** The authenticated HTTPS catalog pins a separate contract for each cloud model. */
fun CloudModelsResponse.validated(expectedLabels: List<String>): CloudModelsResponse {
    require(models.size in 1..4 && models.map { it.version }.distinct().size == models.size) { "云端模型清单无效" }
    require(models.any { it.version == defaultModelVersion }) { "缺少默认云端模型" }
    models.forEach { model ->
        require(model.version.matches(Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,63}"))
            && model.sha256.matches(Regex("[0-9a-f]{64}"))
            && model.labelsSha256.matches(Regex("[0-9a-f]{64}"))
            && model.categoryVersion.matches(Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,63}"))
            && model.status == "frozen" && model.labels == expectedLabels
            && model.threshold.isFinite() && model.threshold in 0f..1f
            && model.displayName.length in 1..64 && model.description.length in 1..160) { "云端模型规格不兼容" }
        val labelsBytes = (model.labels.joinToString("\n") + "\n").toByteArray(Charsets.UTF_8)
        require(com.mobilecloud.recognition.util.ShaUtil.sha256Hex(labelsBytes) == model.labelsSha256) { "云端标签哈希不一致" }
        model.scopePolicy?.let { policy ->
            require(policy.declaredSha256?.matches(Regex("[0-9a-f]{64}")) == true) { "云端范围规则缺少哈希" }
            policy.validate(ScopeIdentity(model.version, model.sha256, model.labelsSha256, model.categoryVersion, "rgb-letterbox-v1"))
        }
    }
    return this
}

fun CloudModelOption.contract() = CloudModelContract(version, sha256, labels, threshold, scopePolicy)

class CloudClassifier(private val api: ApiService) {
    suspend fun classify(file: File, contract: CloudModelContract): Prediction {
        require(file.length() in 1..8L * 1024 * 1024) { "云端图片须小于 8 MiB" }
        val id = UUID.randomUUID().toString()
        val response = api.infer(id.toRequestBody("text/plain".toMediaType()),
            contract.version.toRequestBody("text/plain".toMediaType()),
            MultipartBody.Part.createFormData("image", "capture.jpg", file.asRequestBody("image/jpeg".toMediaType())))
        if (!response.isSuccessful) throw IllegalStateException(when (response.code()) {
            401, 403 -> "云端认证失败，请在我的设备中检查访问令牌"
            409 -> "所选云端模型已不可用，请刷新模型列表后重试"
            413 -> "图片过大，请换一张照片"
            429, 503 -> "云端繁忙或暂不可用，请稍后重试"
            else -> "云端识别失败（HTTP ${response.code()}）"
        })
        return contract.validate(response.body() ?: error("云端未返回识别结果"), id)
    }
}
