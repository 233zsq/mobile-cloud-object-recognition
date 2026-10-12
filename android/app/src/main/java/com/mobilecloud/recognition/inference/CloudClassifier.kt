package com.mobilecloud.recognition.inference

import com.mobilecloud.recognition.data.remote.ApiService
import com.mobilecloud.recognition.data.remote.InferResponse
import java.io.File
import java.util.UUID
import kotlin.math.abs
import kotlin.math.roundToLong
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody

/** Identity and scores must match the bundled contract before a result can be adopted. */
data class CloudModelContract(val version: String, val sha256: String, val labels: List<String>, val threshold: Float) {
    fun validate(response: InferResponse, requestId: String): Prediction {
        require(response.requestId == requestId) { "云端响应编号不匹配，请重试" }
        require(response.modelVersion == version && response.modelSha256 == sha256) { "端云模型版本或哈希不一致，请联系管理员" }
        val scores = response.scores
        require(labels.size == 10 && scores.size == 10 && scores.all { it.isFinite() && it in 0f..1f } && abs(scores.sum() - 1f) <= .0001f) { "云端分数无效" }
        val index = scores.indices.maxBy { scores[it] }
        require(response.predictedId == index && response.labelKey == labels[index] && response.confidence == scores[index]) { "云端类别与分数不一致" }
        require(listOf(response.preprocessMs, response.inferenceMs).all { it.isFinite() && it >= 0 && it < 60_000 }) { "云端耗时无效" }
        return Prediction(index, response.confidence, response.labelKey,
            response.preprocessMs.roundToLong(), response.inferenceMs.roundToLong(),
            (response.preprocessMs + response.inferenceMs).roundToLong(), response.modelVersion)
    }
}

class CloudClassifier(private val api: ApiService) {
    suspend fun classify(file: File, contract: CloudModelContract): Prediction {
        require(file.length() in 1..8L * 1024 * 1024) { "云端图片须小于 8 MiB" }
        val id = UUID.randomUUID().toString()
        val response = api.infer(id.toRequestBody("text/plain".toMediaType()),
            contract.version.toRequestBody("text/plain".toMediaType()),
            MultipartBody.Part.createFormData("image", "capture.jpg", file.asRequestBody("image/jpeg".toMediaType())))
        if (!response.isSuccessful) throw IllegalStateException(when (response.code()) {
            401, 403 -> "云端认证失败，请在我的设备中检查访问令牌"
            409 -> "端云模型版本不一致，请联系管理员"
            413 -> "图片过大，请换一张照片"
            429, 503 -> "云端繁忙或暂不可用，请稍后重试"
            else -> "云端识别失败（HTTP ${response.code()}）"
        })
        return contract.validate(response.body() ?: error("云端未返回识别结果"), id)
    }
}
