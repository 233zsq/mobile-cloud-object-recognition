package com.mobilecloud.recognition

import com.mobilecloud.recognition.inference.ModelMetadata
import com.mobilecloud.recognition.inference.ModelValidator
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelValidatorTest {

    private val validMetadata = ModelMetadata(modelVersion = "v1")

    private fun validate(
        inputShape: IntArray = intArrayOf(1, 224, 224, 3),
        inputDtype: String = ModelValidator.DTYPE_FLOAT32,
        outputShape: IntArray = intArrayOf(1, 10),
        labels: List<String> = List(10) { "label_$it" },
        metadata: ModelMetadata = validMetadata,
    ): List<String> = ModelValidator.validate(inputShape, inputDtype, outputShape, labels, metadata)

    @Test
    fun `valid baseline package passes`() {
        assertTrue(validate().isEmpty())
    }

    @Test
    fun `label count mismatch is rejected`() {
        val errors = validate(labels = List(9) { "label_$it" })
        assertTrue(errors.any { it.contains("不一致") })
    }

    @Test
    fun `quantized input is rejected with explicit message`() {
        val errors = validate(inputDtype = "int8")
        assertTrue(errors.any { it.contains("float32") })
    }

    @Test
    fun `non rgb channels rejected`() {
        val errors = validate(inputShape = intArrayOf(1, 224, 224, 1))
        assertTrue(errors.any { it.contains("通道") })
    }

    @Test
    fun `missing model version rejected`() {
        val errors = validate(metadata = ModelMetadata(modelVersion = null))
        assertTrue(errors.any { it.contains("model_version") })
    }

    @Test
    fun `empty labels rejected`() {
        val errors = validate(labels = emptyList())
        assertTrue(errors.any { it.contains("labels.txt") })
    }

    @Test
    fun `pixel range other than 0-255 rejected`() {
        val metadata = ModelMetadata(
            modelVersion = "v1",
            input = ModelMetadata.InputSpec(pixelRange = listOf(0, 1)),
        )
        val errors = validate(metadata = metadata)
        assertTrue(errors.any { it.contains("pixel_range") })
    }

    @Test
    fun `unknown normalization rejected at load time not first inference`() {
        val metadata = ModelMetadata(
            modelVersion = "v1",
            input = ModelMetadata.InputSpec(normalization = "client: x / 255"),
        )
        val errors = validate(metadata = metadata)
        assertTrue(errors.any { it.contains("inside model") })
    }

    @Test
    fun `declared shape mismatch with tensor is rejected`() {
        val metadata = ModelMetadata(
            modelVersion = "v1",
            input = ModelMetadata.InputSpec(shape = kotlinx.serialization.json.JsonPrimitive("1,192,192,3")),
        )
        val errors = validate(metadata = metadata)
        assertTrue(errors.any { it.contains("input.shape") })
    }

    // ---- official metadata 兼容性 ----

    @Test
    fun `official metadata with array shapes parses`() {
        // 摘录自 models/releases/campus-gpu-v1/metadata.json 的格式特征
        val parsed = ModelMetadata.parse(
            """
            {
              "status": "frozen",
              "model_version": "campus-gpu-v1",
              "sha256": "a58ca2be234d0d7e7db6bdec3853b3e077df6a88321da4f6bd7a8a5d5be51d13",
              "labels_sha256": "3148fcb53e5859041bf7f6af5acbfb952a9d3fbd52a4fd334525b7d3af6a1064",
              "category_version": "campus-10-v2",
              "categories": [{"id": 0, "label_key": "cup", "display_name": "水杯", "definition": "饮水杯"}],
              "input": {
                "version": "rgb-letterbox-v1",
                "shape": [1, 224, 224, 3],
                "dtype": "float32",
                "pixel_range": [0, 255],
                "crop": "none",
                "resize": "bilinear half_pixel_centers; antialias=false; round half up",
                "padding": "center; RGB 128; odd remainder right/bottom",
                "normalization": "inside model: x / 127.5 - 1",
                "byte_order": "little-endian"
              },
              "output": {"shape": [1, 10], "dtype": "float32", "interpretation": "softmax"},
              "low_confidence_threshold": 0.5
            }
            """.trimIndent(),
        )
        assertEquals("campus-gpu-v1", parsed.modelVersion)
        assertTrue(parsed.input.shapeArray!!.contentEquals(intArrayOf(1, 224, 224, 3)))
        assertTrue(parsed.output.shapeArray!!.contentEquals(intArrayOf(1, 10)))
        assertEquals("inside model: x / 127.5 - 1", parsed.input.normalization)
        assertEquals(listOf(0, 255), parsed.input.pixelRange)
        assertEquals(0.5f, parsed.lowConfidenceThreshold!!, 0f)

        val errors = ModelValidator.validate(
            inputShape = intArrayOf(1, 224, 224, 3),
            inputDtype = ModelValidator.DTYPE_FLOAT32,
            outputShape = intArrayOf(1, 10),
            labels = List(10) { "l" },
            metadata = parsed,
        )
        assertTrue(errors.toString(), errors.isEmpty())
    }

    @Test
    fun `legacy string shape still parses`() {
        val parsed = ModelMetadata.parse("""{"model_version":"v0","input":{"shape":"1,224,224,3"}}""")
        assertTrue(parsed.input.shapeArray!!.contentEquals(intArrayOf(1, 224, 224, 3)))
    }

    @Test
    fun `metadata json parsing tolerates unknown fields`() {
        val parsed = ModelMetadata.parse(
            """
            {"status":"placeholder","model_version":"v0","future_field":123,
             "input":{"shape":[1,224,224,3],"dtype":"float32","unknown":true}}
            """.trimIndent(),
        )
        assertEquals("v0", parsed.modelVersion)
        assertTrue(parsed.input.shapeArray!!.contentEquals(intArrayOf(1, 224, 224, 3)))
    }
}