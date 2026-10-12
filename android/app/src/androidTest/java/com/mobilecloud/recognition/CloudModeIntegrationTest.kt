package com.mobilecloud.recognition

import android.graphics.Bitmap
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.camera.PhotoStore
import com.mobilecloud.recognition.data.remote.ApiClient
import com.mobilecloud.recognition.data.settings.ServerConfig
import com.mobilecloud.recognition.inference.*
import java.io.File
import java.net.ServerSocket
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Loopback fixtures exercise the real Retrofit multipart path without team credentials or records. */
@RunWith(AndroidJUnit4::class)
class CloudModeIntegrationTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private fun contract(): CloudModelContract {
        val metadata = ModelMetadata.parse(context.assets.open("models/metadata.json").bufferedReader().use { it.readText() })
        val labels = context.assets.open("models/labels.txt").bufferedReader().use { it.readLines().filter(String::isNotBlank) }
        return CloudModelContract(requireNotNull(metadata.modelVersion), requireNotNull(metadata.sha256), labels, requireNotNull(metadata.lowConfidenceThreshold))
    }
    private fun withServer(status: Int, action: (ApiClient) -> Unit) {
        val contract = contract()
        ServerSocket(0).use { server ->
            server.soTimeout = 10_000
            val executor = Executors.newSingleThreadExecutor()
            val future = executor.submit {
                server.accept().use { socket ->
                    socket.soTimeout = 10_000
                    val input = socket.getInputStream()
                    val header = StringBuilder()
                    while (!header.endsWith("\r\n\r\n")) {
                        val value = input.read()
                        check(value >= 0)
                        header.append(value.toChar())
                    }
                    assertTrue(header.startsWith("POST /api/infer HTTP/1.1"))
                    val length = Regex("Content-Length: (\\d+)", RegexOption.IGNORE_CASE).find(header)!!.groupValues[1].toInt()
                    val bytes = ByteArray(length)
                    var read = 0
                    while (read < length) { val count = input.read(bytes, read, length - read); check(count > 0); read += count }
                    val body = bytes.toString(Charsets.ISO_8859_1)
                    assertEquals(3, Regex("Content-Disposition: form-data;").findAll(body).count())
                    assertTrue(body.contains("name=\"image\""))
                    assertTrue(body.contains(contract.version))
                    val boundary = Regex("boundary=([^;\\r\\n]+)").find(header)!!.groupValues[1]
                    val requestId = body.split("--" + boundary).single { it.contains("name=\"request_id\"") }
                        .substringAfter("\r\n\r\n").trim()
                    val response = JSONObject().put("request_id", requestId).put("model_version", contract.version)
                        .put("model_sha256", contract.sha256).put("predicted_id", 0).put("label_key", "cup")
                        .put("confidence", .9).put("scores", JSONArray(listOf(.9, .1, 0, 0, 0, 0, 0, 0, 0, 0)))
                        .put("preprocess_ms", 12).put("inference_ms", 20).toString().toByteArray()
                    socket.getOutputStream().apply {
                        write(("HTTP/1.1 " + status + " Fixture\r\nContent-Type: application/json\r\nContent-Length: " + response.size + "\r\nConnection: close\r\n\r\n").toByteArray())
                        write(response); flush()
                    }
                }
            }
            try {
                val client = ApiClient()
                assertTrue(client.updateConfig(ServerConfig("http://127.0.0.1:" + server.localPort, "")))
                action(client)
                future.get(15, TimeUnit.SECONDS)
            } finally { executor.shutdownNow() }
        }
    }
    @Test fun multipartRequestProducesValidatedPrediction() = runBlocking {
        val file = File.createTempFile("cloud-request", ".jpg", context.cacheDir)
        val bitmap = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
        try {
            file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }
            withServer(200) { client ->
                val prediction = runBlocking { CloudClassifier(client.api).classify(file, contract()) }
                assertEquals("cup", prediction.label)
                assertEquals(32L, prediction.totalMs)
            }
            withServer(401) { client ->
                try { runBlocking { CloudClassifier(client.api).classify(file, contract()) }; fail("Auth error adopted") }
                catch (e: IllegalStateException) { assertTrue(e.message!!.contains("认证")) }
            }
        } finally { file.delete(); bitmap.recycle() }
    }
    @Test fun cloudCopyBoundsSizeAndRemovesExif() {
        val store = PhotoStore(context)
        val original = File.createTempFile("cloud-photo", ".jpg", context.cacheDir)
        val bitmap = Bitmap.createBitmap(3000, 1000, Bitmap.Config.ARGB_8888)
        try {
            original.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 95, it) }
            androidx.exifinterface.media.ExifInterface(original).apply {
                setAttribute(androidx.exifinterface.media.ExifInterface.TAG_ORIENTATION, "6")
                setAttribute(androidx.exifinterface.media.ExifInterface.TAG_ARTIST, "private-fixture")
                saveAttributes()
            }
            val copy = store.prepareCloudCopy(original)
            try {
                val decoded = requireNotNull(store.decodeUpright(copy))
                assertTrue(decoded.height <= 2048)
                assertTrue(decoded.width < decoded.height)
                assertTrue(copy.length() <= 8L * 1024 * 1024)
                assertNull(androidx.exifinterface.media.ExifInterface(copy).getAttribute(androidx.exifinterface.media.ExifInterface.TAG_ARTIST))
                decoded.recycle()
            } finally { copy.delete() }
        } finally { original.delete(); bitmap.recycle() }
    }
}
