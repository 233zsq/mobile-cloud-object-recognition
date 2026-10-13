package com.mobilecloud.recognition.inference

import com.mobilecloud.recognition.util.ShaUtil
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlin.math.abs

enum class ScopeVerdict { ACCEPTED, UNCERTAIN, UNAVAILABLE }

data class ScopeDecision(
    val verdict: ScopeVerdict,
    val policyVersion: String?,
    val policySha256: String?,
    val reason: String,
) {
    val needsConfirmation: Boolean get() = verdict != ScopeVerdict.ACCEPTED
}

data class ScopeIdentity(val modelVersion: String, val modelSha256: String, val labelsSha256: String,
    val categoryVersion: String?, val preprocessingVersion: String?)

@Serializable
data class ScopePolicy(
    @SerialName("policy_version") val version: String,
    val status: String,
    val rule: String,
    @SerialName("model_version") val modelVersion: String,
    @SerialName("model_sha256") val modelSha256: String,
    @SerialName("labels_sha256") val labelsSha256: String,
    @SerialName("category_version") val categoryVersion: String,
    @SerialName("preprocessing_version") val preprocessingVersion: String,
    @SerialName("confidence_threshold") val confidenceThreshold: Float,
    @SerialName("margin_threshold") val marginThreshold: Float,
) {
    fun validate(identity: ScopeIdentity) {
        require(status == "experimental" && rule == "msp_margin_v1" && version == "scope-basic-v1")
        require(confidenceThreshold.isFinite() && confidenceThreshold in 0f..1f &&
            marginThreshold.isFinite() && marginThreshold in 0f..1f)
        require(modelVersion == identity.modelVersion && modelSha256 == identity.modelSha256 &&
            labelsSha256 == identity.labelsSha256 && categoryVersion == identity.categoryVersion &&
            preprocessingVersion == identity.preprocessingVersion)
    }
}

/** A broken/mismatched policy never prevents the model from returning its original prediction. */
data class ScopePolicyState(val policy: ScopePolicy?, val sha256: String?) {
    fun evaluate(scores: List<Float>): ScopeDecision {
        val active = policy ?: return ScopeDecision(ScopeVerdict.UNAVAILABLE, null, sha256, "确认规则暂不可用，请人工确认")
        if (scores.size != 10 || scores.any { !it.isFinite() || it !in 0f..1f } || abs(scores.sum()-1f) > .0001f)
            return ScopeDecision(ScopeVerdict.UNAVAILABLE, active.version, sha256, "分数核验未通过，请重新识别")
        val ordered = scores.sortedDescending()
        val low = ordered[0] < active.confidenceThreshold
        val close = ordered[0]-ordered[1] < active.marginThreshold
        return ScopeDecision(if (low || close) ScopeVerdict.UNCERTAIN else ScopeVerdict.ACCEPTED,
            active.version, sha256, when {
                low -> "分数较低，可能不在当前 10 类范围内"
                close -> "候选类别接近，请调整角度或人工确认"
                else -> "分数规则通过；仍需以实际物品为准"
            })
    }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }
        val unavailable = ScopePolicyState(null, null)
        fun parse(bytes: ByteArray, expectedHash: String, identity: ScopeIdentity): ScopePolicyState = try {
            val hash = ShaUtil.sha256Hex(bytes)
            require(expectedHash.trim().matches(Regex("[0-9a-f]{64}")) && hash == expectedHash.trim())
            val policy = json.decodeFromString<ScopePolicy>(bytes.toString(Charsets.UTF_8))
            policy.validate(identity)
            ScopePolicyState(policy, hash)
        } catch (_: Exception) { unavailable }
    }
}
