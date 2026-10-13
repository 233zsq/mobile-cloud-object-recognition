package com.mobilecloud.recognition

import android.os.Build
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.camera.decodeAssetUpright
import com.mobilecloud.recognition.inference.*
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Candidate assets belong to the test APK; the installed app keeps its approved v2. */
@RunWith(AndroidJUnit4::class)
class OpenSetHandoverTest {
    @Test fun learnedScopeMatchesIndependentCpuAndRejectsGecko() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.context
        val bundle = ModelBundle.load(context.assets)
        try {
            assertEquals("campus-evolve-v3", bundle.modelVersion)
            assertEquals("learned_knownness_v1", bundle.scopePolicy.policy!!.rule)
            val classifier = TfliteClassifier(bundle)
            val examples = JSONArray(context.assets.open("models/examples/manifest.json").bufferedReader().use { it.readText() })
            var maxScoreError = 0.0
            var maxKnownnessError = 0.0
            var maxImageScoreError = 0.0
            var maxImageKnownnessError = 0.0
            repeat(examples.length()) { index ->
                val sample = examples.getJSONObject(index)
                val bytes = context.assets.open("models/examples/${sample.getString("tensor")}").use { it.readBytes() }
                val input = ByteBuffer.allocateDirect(bytes.size).order(ByteOrder.nativeOrder()).put(bytes).apply { rewind() }
                val outputs = classifier.runOutputs(input)
                val expected = sample.getJSONArray("scores")
                for (i in 0 until 10) maxScoreError = maxOf(maxScoreError, kotlin.math.abs(outputs.scores[i]-expected.getDouble(i)))
                maxKnownnessError = maxOf(maxKnownnessError, kotlin.math.abs(outputs.knownness!!-sample.getDouble("knownness")))
                assertEquals(sample.getInt("predicted_id"), outputs.scores.indices.maxBy { outputs.scores[it] })
                val bitmap = requireNotNull(decodeAssetUpright(context, "models/examples/${sample.getString("image")}"))
                try {
                    val prediction = classifier.classify(bitmap)
                    for (i in 0 until 10) maxImageScoreError = maxOf(maxImageScoreError, kotlin.math.abs(prediction.scores[i]-expected.getDouble(i)))
                    maxImageKnownnessError = maxOf(maxImageKnownnessError, kotlin.math.abs(prediction.scopeDecision!!.knownness!!-sample.getDouble("knownness")))
                    assertEquals(sample.getString("recognition_status"), prediction.scopeDecision!!.verdict.name.lowercase())
                } finally { bitmap.recycle() }
            }
            assertEquals(20, examples.length())
            assertTrue("Reference class score mismatch: $maxScoreError", maxScoreError <= .001)
            assertTrue("Reference scope mismatch: $maxKnownnessError", maxKnownnessError <= .001)
            assertTrue("Image class score mismatch: $maxImageScoreError", maxImageScoreError <= .001)
            assertTrue("Image scope mismatch: $maxImageKnownnessError", maxImageKnownnessError <= .001)
            val gecko = requireNotNull(decodeAssetUpright(context, "open-set-diagnostic/gecko.jpg"))
            val diagnostic = try { classifier.classify(gecko) } finally { gecko.recycle() }
            assertEquals("key", diagnostic.label)
            assertTrue(diagnostic.confidence > .99f)
            assertEquals(ScopeVerdict.UNCERTAIN, diagnostic.scopeDecision!!.verdict)
            val times = mutableListOf<Double>()
            repeat(120) { index ->
                val sample = examples.getJSONObject(index % examples.length())
                val start = SystemClock.elapsedRealtimeNanos()
                val bitmap = requireNotNull(decodeAssetUpright(context, "models/examples/${sample.getString("image")}"))
                try { classifier.classify(bitmap) } finally { bitmap.recycle() }
                if (index >= 20) times += (SystemClock.elapsedRealtimeNanos()-start)/1_000_000.0
            }
            val sorted = times.sorted()
            val report = JSONObject().put("model_version", bundle.modelVersion).put("model_sha256", bundle.sha256)
                .put("policy_sha256", bundle.scopePolicy.sha256).put("device", "${Build.MANUFACTURER} ${Build.MODEL}")
                .put("threads", bundle.numThreads).put("examples", examples.length())
                .put("reference_max_score_error", maxScoreError).put("reference_max_knownness_error", maxKnownnessError)
                .put("image_max_score_error", maxImageScoreError).put("image_max_knownness_error", maxImageKnownnessError)
                .put("gecko_candidate", diagnostic.label).put("gecko_confidence", diagnostic.confidence)
                .put("gecko_knownness", diagnostic.scopeDecision!!.knownness).put("gecko_status", "uncertain")
                .put("warmup", 20).put("measured", 100).put("decode_preprocess_inference_p50_ms", (sorted[49]+sorted[50])/2)
                .put("decode_preprocess_inference_p95_ms", sorted[94]).put("physical_phone_acceptance", false)
            val dir = File(instrumentation.targetContext.filesDir, "open-set-verification").apply { mkdirs() }
            File(dir, "android-candidate.json").writeText(report.toString(2)+"\n")
            println("OPEN_SET_RESULT=${report}")
        } finally { bundle.close() }
    }
}
