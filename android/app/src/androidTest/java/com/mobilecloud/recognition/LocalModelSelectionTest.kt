package com.mobilecloud.recognition

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.camera.decodeAssetUpright
import com.mobilecloud.recognition.inference.ModelRepository
import com.mobilecloud.recognition.inference.ScopeVerdict
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LocalModelSelectionTest {
    @Test fun modelAndPolicySwitchTogetherOfflineAndSelectionSurvivesNewRepository() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val repository = ModelRepository(context)
        val gecko = requireNotNull(decodeAssetUpright(instrumentation.context, "open-set-diagnostic/gecko.jpg"))
        try {
            val v2 = repository.selectVersion("campus-evolve-v2")
            assertEquals("scope-basic-v1", v2.scopePolicyVersion)
            assertEquals("campus-evolve-v2", ModelRepository(context).info().modelVersion)
            val original = repository.classify(gecko)
            assertEquals("key", original.label)
            assertEquals(ScopeVerdict.ACCEPTED, original.scopeDecision!!.verdict)
            val v3 = repository.selectVersion("campus-evolve-v3")
            assertEquals("scope-knownness-v1", v3.scopePolicyVersion)
            val improved = repository.classify(gecko)
            assertEquals(original.scores, improved.scores)
            assertEquals(ScopeVerdict.UNCERTAIN, improved.scopeDecision!!.verdict)
            assertEquals("campus-evolve-v3", improved.modelVersion)
        } finally { gecko.recycle(); repository.selectVersion("campus-evolve-v3") }
    }
}
