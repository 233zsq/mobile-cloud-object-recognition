package com.mobilecloud.recognition

import com.mobilecloud.recognition.inference.CloudModelContract
import com.mobilecloud.recognition.data.remote.InferResponse
import org.junit.Assert.*
import org.junit.Test

class CloudContractTest {
    private val labels = listOf("cup", "umbrella", "book", "pencil_case", "mouse", "keyboard", "earphones", "charger", "key", "backpack")
    private val contract = CloudModelContract("campus-evolve-v2", "a".repeat(64), labels, .6f)
    private val valid = InferResponse("request-1", contract.version, contract.sha256, 0, "cup", .9f,
        listOf(.9f, .1f, 0f, 0f, 0f, 0f, 0f, 0f, 0f, 0f), 12.4, 20.4, false)
    private fun rejected(value: InferResponse) {
        try { contract.validate(value, "request-1"); fail("Untrusted result adopted") }
        catch (_: IllegalArgumentException) { }
    }
    @Test fun correctResponseUsesComputeTimeAndBundledThreshold() {
        val prediction = contract.validate(valid, "request-1")
        assertEquals(33L, prediction.totalMs)
        assertEquals("cup", prediction.label)
        assertFalse(prediction.isLowConfidence(contract.threshold))
    }
    @Test fun mismatchedRequestCannotProduceRecord() { rejected(valid.copy(requestId = "another-request")) }
    @Test fun matchingVersionWithWrongHashIsRejected() { rejected(valid.copy(modelSha256 = "b".repeat(64))) }
    @Test fun differentModelIsRejected() { rejected(valid.copy(modelVersion = "campus-gpu-v1")) }
    @Test fun selectedModelThresholdAndMissingFlagAreChecked() { rejected(valid.copy(lowConfidence = true)); rejected(valid.copy(lowConfidence = null)) }
    @Test fun wrongLabelOrIndexIsRejected() { rejected(valid.copy(labelKey = "book")); rejected(valid.copy(predictedId = 2)) }
    @Test fun invalidProbabilityVectorIsRejected() {
        rejected(valid.copy(scores = listOf(.9f)))
        rejected(valid.copy(scores = List(10) { .9f }))
        rejected(valid.copy(scores = valid.scores.toMutableList().apply { this[1] = Float.NaN }))
        rejected(valid.copy(confidence = .8f))
    }
    @Test fun invalidTimingIsRejected() { rejected(valid.copy(preprocessMs = Double.POSITIVE_INFINITY)); rejected(valid.copy(inferenceMs = -1.0)) }
}
