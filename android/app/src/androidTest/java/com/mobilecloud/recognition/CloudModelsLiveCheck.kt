package com.mobilecloud.recognition

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.data.settings.SettingsStore
import com.mobilecloud.recognition.inference.CloudClassifier
import com.mobilecloud.recognition.inference.contract
import com.mobilecloud.recognition.inference.validated
import java.io.File
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in check on an already-authorized emulator. Never installs or prints credentials. */
@RunWith(AndroidJUnit4::class)
class CloudModelsLiveCheck {
    @Test fun eachSelectedModelReturnsItsOwnVerifiedIdentityWithoutWritingRecords() = runBlocking {
        assumeTrue(InstrumentationRegistry.getArguments().getString("verifyCloudModels") == "true")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        AppGraph.init(context)
        val config = AppGraph.settings.currentConfig()
        assumeTrue("Use an already-configured group emulator", config.baseUrl.trimEnd('/') == SettingsStore.TEAM_SERVER_URL && config.token.isNotBlank())
        AppGraph.apiClient.updateConfig(config)
        val catalog = AppGraph.apiClient.api.models().validated(AppGraph.categoryCatalog.categories.map { it.labelKey })
        assertTrue(catalog.models.map { it.version }.containsAll(listOf("campus-evolve-v2", "campus-evolve-v3")))
        val file = File(context.cacheDir, "public-model-check.jpg")
        context.assets.open("models/examples/oi-30d38acdacfe06d0.jpg").use { input -> file.outputStream().use { input.copyTo(it) } }
        val outcomes = mutableListOf<JsonObject>()
        try {
            for (model in catalog.models) {
                assertTrue(model.available)
                val prediction = CloudClassifier(AppGraph.apiClient.api).classify(file, model.contract())
                assertEquals(model.version, prediction.modelVersion)
                outcomes += buildJsonObject { put("model_version", prediction.modelVersion); put("model_sha256", model.sha256); put("predicted_id", prediction.index); put("confidence", prediction.confidence) }
            }
            val v3=catalog.models.single { it.version=="campus-evolve-v3" }
            val samples=org.json.JSONArray(context.assets.open("models/examples/manifest.json").bufferedReader().use { it.readText() })
            var uncertain=0
            repeat(samples.length()) { index ->
                val sample=samples.getJSONObject(index)
                context.assets.open("models/examples/${sample.getString("image")}").use { input -> file.outputStream().use { input.copyTo(it) } }
                val prediction=CloudClassifier(AppGraph.apiClient.api).classify(file,v3.contract())
                assertEquals(sample.getInt("predicted_id"),prediction.index)
                assertEquals(sample.getString("recognition_status"),prediction.scopeDecision!!.verdict.name.lowercase())
                assertTrue(kotlin.math.abs(prediction.scopeDecision!!.knownness!!-sample.getDouble("knownness"))<=.001)
                if(prediction.scopeDecision!!.needsConfirmation) uncertain++
            }
            assertTrue("Known uncertain samples must remain uncertain through real API",uncertain>=2)
        } finally { file.delete() }
        val output = File(requireNotNull(context.getExternalFilesDir("ui-checks")), "cloud-models-live.json")
        output.writeText(buildJsonObject { put("record_writes", 0); put("models", JsonArray(outcomes)) }.toString())
    }
}
