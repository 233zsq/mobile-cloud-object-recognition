package com.mobilecloud.recognition

import com.mobilecloud.recognition.inference.*
import com.mobilecloud.recognition.util.ShaUtil
import org.junit.Assert.*
import org.junit.Test

class ScopePolicyTest {
    private val identity = ScopeIdentity("campus-evolve-v2", "a".repeat(64), "b".repeat(64), "campus-10-v4", "rgb-letterbox-v1")
    private val text = """{"policy_version":"scope-basic-v1","status":"experimental","rule":"msp_margin_v1",
        "model_version":"campus-evolve-v2","model_sha256":"${identity.modelSha256}",
        "labels_sha256":"${identity.labelsSha256}","category_version":"campus-10-v4",
        "preprocessing_version":"rgb-letterbox-v1","confidence_threshold":0.55,"margin_threshold":0.2}"""
    private fun parse(value: String = text, hash: String = ShaUtil.sha256Hex(value.toByteArray()), id: ScopeIdentity = identity) =
        ScopePolicyState.parse(value.toByteArray(), hash, id)

    @Test fun confidentSeparatedScoresAreAcceptedButCloseOrLowScoresRequireConfirmation() {
        val state = parse()
        assertEquals(ScopeVerdict.ACCEPTED, state.evaluate(listOf(.9f,.1f)+List(8){0f}).verdict)
        assertEquals(ScopeVerdict.UNCERTAIN, state.evaluate(listOf(.56f,.44f)+List(8){0f}).verdict)
        assertEquals(ScopeVerdict.UNCERTAIN, state.evaluate(List(10){.1f}).verdict)
    }

    @Test fun matchingVersionCannotHideDifferentModelLabelsCategoryOrPreprocessing() {
        listOf(identity.copy(modelSha256 = "c".repeat(64)), identity.copy(labelsSha256 = "c".repeat(64)),
            identity.copy(categoryVersion = "older"), identity.copy(preprocessingVersion = "different")).forEach {
            assertNull(parse(id = it).policy)
        }
    }

    @Test fun wrongHashMalformedPolicyAndInvalidThresholdDisablePolicy() {
        assertNull(parse(hash = "c".repeat(64)).policy)
        assertNull(parse("{}").policy)
        assertNull(parse(text.replace("0.55", "1.55")).policy)
    }

    @Test fun invalidScoresAndUnavailableRulesNeverClaimAutomaticConfirmation() {
        val state = parse()
        listOf(emptyList(), List(10){.9f}, listOf(Float.NaN)+List(9){0f}).forEach {
            assertEquals(ScopeVerdict.UNAVAILABLE, state.evaluate(it).verdict)
        }
        assertTrue(ScopePolicyState.unavailable.evaluate(listOf(.9f,.1f)+List(8){0f}).needsConfirmation)
    }

    @Test fun uncertainFramesCannotBecomeStableByRepeatingTheSameGuess() {
        val scores = listOf(.56f,.44f)+List(8){0f}
        val prediction = Prediction(0,.56f,"cup",5,5,10,"campus-evolve-v2",scores,parse().evaluate(scores))
        val tracker = LiveResultTracker()
        repeat(5) { assertFalse(tracker.observe(prediction,.5f,it*500L).stable) }
    }

    @Test fun learnedRuleCanRejectOneHundredPercentClassScoreAndFailsClosedWithoutKnownness() {
        val learned = text.replace("scope-basic-v1", "scope-knownness-v1").replace("msp_margin_v1", "learned_knownness_v1")
            .replace("\"margin_threshold\":0.2", "\"margin_threshold\":0.2,\"knownness_threshold\":0.85")
        val state = parse(learned)
        val scores = List(10) { if (it == 8) 1f else 0f }
        assertEquals(ScopeVerdict.UNCERTAIN, state.evaluate(scores, .429f).verdict)
        assertEquals(ScopeVerdict.ACCEPTED, state.evaluate(scores, .85f).verdict)
        assertEquals(ScopeVerdict.UNAVAILABLE, state.evaluate(scores).verdict)
        assertEquals(ScopeVerdict.UNAVAILABLE, state.evaluate(scores, Float.NaN).verdict)
    }
}
