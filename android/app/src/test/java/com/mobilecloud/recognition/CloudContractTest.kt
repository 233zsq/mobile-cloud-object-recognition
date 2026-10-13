package com.mobilecloud.recognition

import com.mobilecloud.recognition.inference.CloudModelContract
import com.mobilecloud.recognition.data.remote.InferResponse
import com.mobilecloud.recognition.data.remote.CloudScopeDecision
import com.mobilecloud.recognition.inference.ScopePolicy
import com.mobilecloud.recognition.inference.ScopeVerdict
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

    @Test fun cloudLearnedRulePreservesCandidateButRequiresConfirmationAndRejectsContradictoryResponse() {
        val hash = "c".repeat(64)
        val policy = ScopePolicy("scope-knownness-v1", "experimental", "learned_knownness_v1", contract.version,
            contract.sha256, "b".repeat(64), "campus-10-v4", "rgb-letterbox-v1", .55f, .20f, .85f, hash)
        val selected = contract.copy(scopePolicy = policy)
        val evidence = CloudScopeDecision("uncertain", true, policy.version, hash, .429f)
        val response = valid.copy(scores = listOf(1f)+List(9){0f}, confidence = 1f, scopeDecision = evidence)
        val prediction = selected.validate(response, "request-1")
        assertEquals(ScopeVerdict.UNCERTAIN, prediction.scopeDecision!!.verdict)
        assertEquals("cup", prediction.label)
        listOf(evidence.copy(status = "accepted", needsConfirmation = false), evidence.copy(policySha256 = "d".repeat(64))).forEach {
            try { selected.validate(response.copy(scopeDecision = it), "request-1"); fail("Contradictory scope adopted") }
            catch (_: IllegalArgumentException) { }
        }
    }

    @Test fun legacyCloudWithoutScopeEvidenceAlwaysNeedsConfirmation() {
        assertEquals(ScopeVerdict.UNAVAILABLE, contract.validate(valid, "request-1").scopeDecision!!.verdict)
    }
}
