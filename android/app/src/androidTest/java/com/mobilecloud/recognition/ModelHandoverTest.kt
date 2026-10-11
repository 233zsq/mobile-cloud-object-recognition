package com.mobilecloud.recognition

import android.os.Build
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.camera.decodeAssetUpright
import com.mobilecloud.recognition.data.CategoryFile
import com.mobilecloud.recognition.inference.ConsistencyCheck
import com.mobilecloud.recognition.inference.ExampleSample
import com.mobilecloud.recognition.inference.ModelBundle
import com.mobilecloud.recognition.inference.TfliteClassifier
import java.io.File
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Requires the approved local delivery payload, including debug-only examples. */
@RunWith(AndroidJUnit4::class)
class ModelHandoverTest {
    @Test
    fun deliveredModelMatchesReferencesAndRecordsTiming() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val bundle = ModelBundle.load(context.assets)
        try {
            val categories = CategoryFile.parse(context.assets.open("categories.json").bufferedReader().use { it.readText() })
            assertEquals(bundle.labels, categories.categories.sortedBy { it.id }.map { it.labelKey })
            assertEquals(10, bundle.outputClasses)
            val summary = ConsistencyCheck(context).run(bundle) { }
            assertEquals(20, summary.reference.total)
            assertEquals(20, summary.imageChain.total)
            assertTrue((summary.reference.failures + summary.imageChain.failures).joinToString("\n"), summary.allPassed)

            val samples = ExampleSample.parse(context.assets.open("models/examples/manifest.json").bufferedReader().use { it.readText() })
            val classifier = TfliteClassifier(bundle)
            val preprocessing = mutableListOf<Double>()
            val inference = mutableListOf<Double>()
            val total = mutableListOf<Double>()
            repeat(120) { index ->
                val started = SystemClock.elapsedRealtimeNanos()
                val bitmap = requireNotNull(decodeAssetUpright(context, "models/examples/${samples[index % samples.size].image}"))
                try {
                    val result = classifier.classify(bitmap)
                    val elapsed = (SystemClock.elapsedRealtimeNanos() - started) / 1_000_000.0
                    if (index >= 20) {
                        preprocessing += result.preprocessMs.toDouble()
                        inference += result.inferenceMs.toDouble()
                        total += elapsed
                    }
                } finally {
                    bitmap.recycle()
                }
            }
            fun statistics(values: List<Double>): JSONObject {
                val ordered = values.sorted()
                return JSONObject().put("p50", (ordered[49] + ordered[50]) / 2)
                    .put("p95", ordered[94]).put("min", ordered.first()).put("max", ordered.last())
            }
            val device = "${Build.MANUFACTURER} ${Build.MODEL} / Android ${Build.VERSION.RELEASE} SDK ${Build.VERSION.SDK_INT}"
            val report = JSONObject().put("model_version", bundle.modelVersion).put("model_sha256", bundle.sha256)
                .put("device", device).put("fingerprint", Build.FINGERPRINT).put("threads", bundle.numThreads)
                .put("runtime", summary.runtime).put("run_id", summary.runId).put("warmup", 20).put("measured", 100)
                .put("unit", "ms").put("includes_network", false)
                .put("preprocessing", statistics(preprocessing)).put("inference", statistics(inference))
                .put("decode_preprocess_and_inference", statistics(total))
                .put("measurement_notes", JSONArray().put("Classifier stage timings use millisecond resolution.")
                    .put("Total includes image decode and EXIF; measured with elapsedRealtimeNanos.")
                    .put("Emulator results do not satisfy physical-phone performance acceptance."))
            File(summary.outputDir, "benchmark.json").writeText(report.toString(2) + "\n")
            println("MODEL_HANDOVER_RESULT=${summary.outputDir.absolutePath}")
        } finally {
            bundle.close()
        }
    }
}
