package com.mobilecloud.recognition

import com.mobilecloud.recognition.inference.ModelMetadata
import com.mobilecloud.recognition.inference.ModelValidator
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelValidatorTest {

    private val validMetadata = ModelMetadata(modelVersion = "v1")

    @Test
    fun `valid baseline package passes`() {
        val errors = ModelValidator.validate(
            inputShape = intArrayOf(1, 224, 224, 3),
            inputDtype = ModelValidator.DTYPE_FLOAT32,
            outputShape = intArrayOf(1, 10),
            labels = List(10) { "label_$it" },
            metadata = validMetadata,
        )
        assertTrue(errors.isEmpty())
    }

    @Test
    fun `label count mismatch is rejected`() {
        val errors = ModelValidator.validate(
            inputShape = intArrayOf(1, 224, 224, 3),
            inputDtype = ModelValidator.DTYPE_FLOAT32,
            outputShape = intArrayOf(1, 10),
            labels = List(9) { "label_$it" },
            metadata = validMetadata,
        )
        assertTrue(errors.any { it.contains("不一致") })
    }

    @Test
    fun `quantized input is rejected with explicit message`() {
        val errors = ModelValidator.validate(
            inputShape = intArrayOf(1, 224, 224, 3),
            inputDtype = "int8",
            outputShape = intArrayOf(1, 10),
            labels = List(10) { "l" },
            metadata = validMetadata,
        )
        assertTrue(errors.any { it.contains("float32") })
    }

    @Test
    fun `non rgb channels rejected`() {
        val errors = ModelValidator.validate(
            inputShape = intArrayOf(1, 224, 224, 1),
            inputDtype = ModelValidator.DTYPE_FLOAT32,
            outputShape = intArrayOf(1, 10),
            labels = List(10) { "l" },
            metadata = validMetadata,
        )
        assertTrue(errors.any { it.contains("通道") })
    }

    @Test
    fun `missing model version rejected`() {
        val errors = ModelValidator.validate(
            inputShape = intArrayOf(1, 224, 224, 3),
            inputDtype = ModelValidator.DTYPE_FLOAT32,
            outputShape = intArrayOf(1, 10),
            labels = List(10) { "l" },
            metadata = ModelMetadata(modelVersion = null),
        )
        assertTrue(errors.any { it.contains("model_version") })
    }

    @Test
    fun `empty labels rejected`() {
        val errors = ModelValidator.validate(
            inputShape = intArrayOf(1, 224, 224, 3),
            inputDtype = ModelValidator.DTYPE_FLOAT32,
            outputShape = intArrayOf(1, 10),
            labels = emptyList(),
            metadata = validMetadata,
        )
        assertTrue(errors.any { it.contains("labels.txt") })
    }

    @Test
    fun `metadata json parsing tolerates unknown fields`() {
        val parsed = ModelMetadata.parse(
            """
            {"status":"placeholder","model_version":"v0","future_field":123,
             "input":{"shape":"1,224,224,3","dtype":"float32","unknown":true}}
            """.trimIndent(),
        )
        assertEquals("v0", parsed.modelVersion)
        assertEquals("1,224,224,3", parsed.input.shape)
    }
}
