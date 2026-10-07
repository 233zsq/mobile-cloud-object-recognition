package com.mobilecloud.recognition

import com.mobilecloud.recognition.util.PreprocessMath
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PreprocessMathTest {

    @Test
    fun `exif rotate 90 maps to 90 degrees`() {
        assertEquals(90, PreprocessMath.transformForExif(PreprocessMath.EXIF_ROTATE_90).degrees)
    }

    @Test
    fun `exif rotate 270 maps to 270 degrees`() {
        assertEquals(270, PreprocessMath.transformForExif(PreprocessMath.EXIF_ROTATE_270).degrees)
    }

    @Test
    fun `exif normal is identity`() {
        val t = PreprocessMath.transformForExif(PreprocessMath.EXIF_NORMAL)
        assertEquals(0, t.degrees)
        assertFalse(t.flipHorizontal)
        assertFalse(t.flipVertical)
    }

    @Test
    fun `exif flip vertical is 180 plus flip`() {
        val t = PreprocessMath.transformForExif(PreprocessMath.EXIF_FLIP_VERTICAL)
        assertEquals(180, t.degrees)
        assertTrue(t.flipHorizontal)
    }

    @Test
    fun `center crop of landscape keeps centered square`() {
        val crop = PreprocessMath.centerCropSpec(400, 200)
        assertEquals(100, crop.left)
        assertEquals(0, crop.top)
        assertEquals(200, crop.size)
    }

    @Test
    fun `center crop of portrait keeps centered square`() {
        val crop = PreprocessMath.centerCropSpec(300, 600)
        assertEquals(0, crop.left)
        assertEquals(150, crop.top)
        assertEquals(300, crop.size)
    }

    @Test
    fun `mobilenet normalization maps to minus one one range`() {
        val preset = PreprocessMath.NormalizationPreset.MOBILENET_V2_MINUS1_1
        assertEquals(-1f, preset.apply(0), 1e-4f)
        assertEquals(1f, preset.apply(255), 1e-4f)
        // 127 逼近中点，偏差为 1/255
        assertEquals(-1f / 255f, preset.apply(127), 1e-4f)
    }

    @Test
    fun `unit normalization maps 255 to one`() {
        val preset = PreprocessMath.NormalizationPreset.UNIT_0_1
        assertEquals(1f, preset.apply(255), 1e-4f)
        assertEquals(0f, preset.apply(0), 1e-4f)
    }

    @Test
    fun `normalization preset defaults to mobilenet`() {
        assertEquals(
            PreprocessMath.NormalizationPreset.MOBILENET_V2_MINUS1_1,
            PreprocessMath.NormalizationPreset.fromName(null),
        )
        assertEquals(
            PreprocessMath.NormalizationPreset.UNIT_0_1,
            PreprocessMath.NormalizationPreset.fromName("unit_0_1"),
        )
    }

    @Test
    fun `shape string parsing`() {
        assertTrue(PreprocessMath.parseShape("1,224,224,3")!!.contentEquals(intArrayOf(1, 224, 224, 3)))
        assertTrue(PreprocessMath.parseShape(null) == null)
        assertTrue(PreprocessMath.parseShape("1x224x224x3")!!.contentEquals(intArrayOf(1, 224, 224, 3)))
    }
}
