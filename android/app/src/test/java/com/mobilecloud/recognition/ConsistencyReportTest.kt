package com.mobilecloud.recognition

import com.mobilecloud.recognition.inference.ConsistencyReport
import com.mobilecloud.recognition.inference.ExampleSample
import com.mobilecloud.recognition.inference.LetterboxEncoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConsistencyReportTest {

    private val contract = Json.parseToJsonElement(
        """
        {"version":"rgb-letterbox-v1","orientation":"EXIF transpose","color_order":"RGB",
         "shape":[1,224,224,3],"dtype":"float32","pixel_range":[0,255],"crop":"none",
         "resize":"bilinear half_pixel_centers; antialias=false; round half up",
         "padding":"center; RGB 128; odd remainder right/bottom",
         "normalization":"inside model: x / 127.5 - 1","byte_order":"little-endian"}
        """.trimIndent(),
    )

    @Test
    fun `contract tensor byte count matches 224 rgb float32`() {
        assertEquals(602112, LetterboxEncoder.CONTRACT_BYTES)
        assertEquals(224 * 224 * 3 * 4, LetterboxEncoder.CONTRACT_BYTES)
    }

    @Test
    fun `reference report carries tensor sha and embeds contract verbatim`() {
        val report = ConsistencyReport.build(
            mode = ConsistencyReport.MODE_REFERENCE_TENSOR,
            runId = "android-mi13-20261009-120000",
            device = "Xiaomi 2210132C / Android 15 (SDK 35)",
            runtime = "LiteRT java org.tensorflow.lite 1.4.1 / threads=4",
            modelSha256 = "a58ca2be",
            labelsSha256 = "3148fcb5",
            inputContract = contract,
            samples = listOf(
                ConsistencyReport.SampleReport(
                    sampleId = "commons-101801303",
                    scores = FloatArray(10) { 0.1f },
                    tensorSha256 = "tensor-sha",
                ),
            ),
        )
        val text = Json.encodeToString(JsonObject.serializer(), report)
        val parsed = Json.parseToJsonElement(text) as JsonObject

        assertEquals("reference_tensor", parsed["mode"]!!.jsonPrimitive.content)
        assertEquals(contract, parsed["input_contract"])
        val sample = parsed["samples"]!!.jsonArray[0] as JsonObject
        assertEquals("commons-101801303", sample["sample_id"]!!.jsonPrimitive.content)
        assertEquals(10, sample["scores"]!!.jsonArray.size)
        assertEquals("tensor-sha", sample["tensor_sha256"]!!.jsonPrimitive.content)
        assertFalse(sample.containsKey("tensor_file"))
    }

    @Test
    fun `image chain report references tensor file`() {
        val report = ConsistencyReport.build(
            mode = ConsistencyReport.MODE_IMAGE_CHAIN,
            runId = "android-mi13-20261009-120000",
            device = "device",
            runtime = "runtime",
            modelSha256 = "m",
            labelsSha256 = "l",
            inputContract = contract,
            samples = listOf(
                ConsistencyReport.SampleReport(
                    sampleId = "oi-30d38acdacfe06d0",
                    scores = FloatArray(10) { 0.1f },
                    tensorFile = "oi-30d38acdacfe06d0.bin",
                ),
            ),
        )
        val parsed = Json.parseToJsonElement(Json.encodeToString(JsonObject.serializer(), report)) as JsonObject
        val sample = parsed["samples"]!!.jsonArray[0] as JsonObject
        assertEquals("oi-30d38acdacfe06d0.bin", sample["tensor_file"]!!.jsonPrimitive.content)
        assertFalse(sample.containsKey("tensor_sha256"))
    }

    @Test
    fun `local verdict follows verifier thresholds`() {
        val golden = List(10) { 0.1 }
        // 下标 3 为最大值且与 golden 的差在 0.001 内
        val passScores = FloatArray(10) { i -> if (i == 3) 0.1005f else 0.09995f }
        val pass = ConsistencyReport.evaluate(passScores, golden, 3, 0.0005)
        assertTrue(pass.passed)
        assertTrue(pass.top1Same)

        val top1Wrong = FloatArray(10) { i -> if (i == 5) 0.5f else 0.0555f }
        assertFalse(ConsistencyReport.evaluate(top1Wrong, golden, 3, 0.0).passed)

        val inputTooDifferent = ConsistencyReport.evaluate(passScores, golden, 3, 0.002)
        assertFalse(inputTooDifferent.passed)

        val scoreTooDifferent = ConsistencyReport.evaluate(
            FloatArray(10) { i -> if (i == 3) 0.11f else 0.0989f },
            golden,
            3,
            0.0,
        )
        assertFalse(scoreTooDifferent.passed)
    }

    @Test
    fun `max float diff and range read little endian`() {
        val a = java.nio.ByteBuffer.allocate(8).order(java.nio.ByteOrder.LITTLE_ENDIAN)
            .putFloat(128f).putFloat(255f).array()
        val b = java.nio.ByteBuffer.allocate(8).order(java.nio.ByteOrder.LITTLE_ENDIAN)
            .putFloat(128.0005f).putFloat(254f).array()
        assertEquals(1.0, ConsistencyReport.maxFloatDiff(a, b), 1e-9)
        val (min, max) = ConsistencyReport.floatRange(a)
        assertEquals(128f, min, 0f)
        assertEquals(255f, max, 0f)
    }
}

class ExampleManifestTest {

    @Test
    fun `parses official manifest array with extra fields`() {
        val samples = ExampleSample.parse(
            """
            [
              {"sample_id":"oi-30d38acdacfe06d0","category_id":0,"image":"oi-30d38acdacfe06d0.jpg",
               "tensor":"oi-30d38acdacfe06d0.bin","image_sha256":"abc",
               "tensor_sha256":"e9176625","scores":[0.9995,0.0000156],"predicted_id":0,
               "source_url":"https://example.com","author":"Someone","license":"CC-BY"}
            ]
            """.trimIndent(),
        )
        assertEquals(1, samples.size)
        val s = samples[0]
        assertEquals("oi-30d38acdacfe06d0", s.sampleId)
        assertEquals("oi-30d38acdacfe06d0.bin", s.tensor)
        assertEquals("e9176625", s.tensorSha256)
        assertEquals(0, s.predictedId)
        assertEquals(2, s.scores.size)
    }

    @Test
    fun `broken manifest is rejected with message`() {
        val error = runCatching { ExampleSample.parse("{not json") }.exceptionOrNull()
        assertTrue(error is IllegalArgumentException)
        assertTrue(error!!.message!!.contains("样例清单"))
    }
}