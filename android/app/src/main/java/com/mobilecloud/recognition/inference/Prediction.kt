package com.mobilecloud.recognition.inference

data class Prediction(
    val index: Int,
    val confidence: Float,
    val label: String,
    val preprocessMs: Long,
    val inferenceMs: Long,
    val totalMs: Long,
    val modelVersion: String,
    val scores: List<Float> = emptyList(),
    val scopeDecision: ScopeDecision? = null,
) {
    fun isLowConfidence(threshold: Float): Boolean = confidence < threshold
}
