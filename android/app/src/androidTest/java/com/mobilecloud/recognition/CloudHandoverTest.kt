package com.mobilecloud.recognition

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.data.remote.ApiClient
import com.mobilecloud.recognition.data.settings.ServerConfig
import com.mobilecloud.recognition.data.settings.SettingsStore
import com.mobilecloud.recognition.inference.ExampleSample
import com.mobilecloud.recognition.inference.CloudClassifier
import com.mobilecloud.recognition.inference.CloudModelContract
import com.mobilecloud.recognition.inference.ModelRepository
import com.mobilecloud.recognition.camera.PhotoStore
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Optional real-host check. Credentials arrive in app-private storage, never APK assets. */
@RunWith(AndroidJUnit4::class)
class CloudHandoverTest {
    @Test
    fun configuredServerMatchesDeliveredModelWithoutWritingRecords() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val settings = SettingsStore(context)
        val privateConfig = File(context.filesDir, "handover-server-config.json")
        val config = if (privateConfig.isFile) {
            try {
                val value = JSONObject(privateConfig.readText())
                ServerConfig(value.getString("base_url"), value.getString("token"))
            } catch (_: Exception) {
                // JSONObject parse errors may quote the full input, including credentials.
                throw IllegalArgumentException("Private cloud configuration is invalid")
            } finally {
                privateConfig.delete()
            }
        } else settings.currentConfig()
        assumeTrue("Configure an approved HTTPS host and token before running the cloud handover check.",
            config.baseUrl.startsWith("https://") && config.token.isNotBlank())
        val client = ApiClient()
        assertTrue(client.updateConfig(config))
        val health = client.api.health()
        assertEquals("ok", health.status)
        assertEquals(true, health.modelLoaded)
        // Save only after authentication/TLS and all reference predictions have passed.
        val metadata = JSONObject(context.assets.open("models/metadata.json").bufferedReader().use { it.readText() })
        val samples = ExampleSample.parse(context.assets.open("models/examples/manifest.json").bufferedReader().use { it.readText() })
        val http = OkHttpClient.Builder().callTimeout(30, TimeUnit.SECONDS).build()
        val results = JSONArray()
        val productResults = JSONArray()
        val labels = context.assets.open("models/labels.txt").bufferedReader().use { it.readLines().filter(String::isNotBlank) }
        val contract = CloudModelContract(metadata.getString("model_version"), metadata.getString("sha256"), labels,
            metadata.getDouble("low_confidence_threshold").toFloat())
        val photoStore = PhotoStore(context)
        val localModel = ModelRepository(context)
        for (sample in samples) {
            val bytes = context.assets.open("models/examples/${sample.image}").use { it.readBytes() }
            val form = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("request_id", UUID.randomUUID().toString())
                .addFormDataPart("model_version", metadata.getString("model_version"))
                .addFormDataPart("image", "sample.jpg", bytes.toRequestBody("image/jpeg".toMediaType()))
                .build()
            val request = Request.Builder().url(config.baseUrl.trimEnd('/') + "/api/infer")
                .header("Authorization", "Bearer ${config.token}").post(form).build()
            http.newCall(request).execute().use { response ->
                assertEquals("HTTPS inference returned an error", 200, response.code)
                val value = JSONObject(requireNotNull(response.body).string())
                assertEquals(metadata.getString("sha256"), value.getString("model_sha256"))
                assertEquals(metadata.getString("model_version"), value.getString("model_version"))
                assertEquals(sample.predictedId, value.getInt("predicted_id"))
                val scores = value.getJSONArray("scores")
                assertEquals(sample.scores.size, scores.length())
                val difference = sample.scores.indices.maxOf { kotlin.math.abs(sample.scores[it] - scores.getDouble(it)) }
                assertTrue("Cloud scores differ from the approved reference", difference <= .001)
                results.put(JSONObject().put("sample_id", sample.sampleId).put("max_score_difference", difference).put("passed", true))
            }
            val original = File.createTempFile("handover-source", ".jpg", context.cacheDir).apply { writeBytes(bytes) }
            try {
                val transport = photoStore.prepareCloudCopy(original)
                try {
                    val cloud = CloudClassifier(client.api).classify(transport, contract)
                    val bitmap = requireNotNull(photoStore.decodeUpright(transport))
                    val local = try { localModel.classify(bitmap) } finally { bitmap.recycle() }
                    assertEquals("Transport-copy Top-1 differs", local.index, cloud.index)
                    val difference = kotlin.math.abs(local.confidence - cloud.confidence)
                    assertTrue("Transport-copy confidence differs", difference <= .001)
                    productResults.put(JSONObject().put("sample_id", sample.sampleId).put("predicted_id", cloud.index)
                        .put("confidence_difference", difference).put("passed", true))
                } finally { transport.delete() }
            } finally { original.delete() }
        }
        settings.setConfig(config)
        val report = JSONObject().put("scope", InstrumentationRegistry.getArguments().getString("execution_scope", "Android device; physical/emulator context recorded separately"))
            .put("device", "${Build.MANUFACTURER} ${Build.MODEL}; Android ${Build.VERSION.RELEASE}")
            .put("base_url", config.baseUrl).put("model_version", metadata.getString("model_version"))
            .put("model_sha256", metadata.getString("sha256")).put("tls_verified", true)
            .put("authenticated", true).put("records_written", 0).put("samples", results)
            .put("product_client_transport_copies", productResults).put("passed", true)
        File(context.getExternalFilesDir(null), "cloud-handover-${System.currentTimeMillis()}.json").writeText(report.toString(2) + "\n")
    }
}
