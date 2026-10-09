package com.mobilecloud.recognition

import com.mobilecloud.recognition.util.PreprocessMath
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PreprocessMathTest {

    // ---- EXIF 方向 ----

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

    // ---- letterbox 几何（契约 rgb-letterbox-v1）----

    @Test
    fun `landscape letterbox fits height and pads top bottom`() {
        // 400x200 -> scale=224/400=0.56 -> inner 224x112, offsetY=56
        val geo = PreprocessMath.letterboxGeometry(400, 200, 224)
        assertEquals(224, geo.innerWidth)
        assertEquals(112, geo.innerHeight)
        assertEquals(0, geo.offsetX)
        assertEquals(56, geo.offsetY)
    }

    @Test
    fun `portrait letterbox fits width and pads left right`() {
        // 300x600 -> scale=224/600 -> inner 112x224, offsetX=56
        val geo = PreprocessMath.letterboxGeometry(300, 600, 224)
        assertEquals(112, geo.innerWidth)
        assertEquals(224, geo.innerHeight)
        assertEquals(56, geo.offsetX)
        assertEquals(0, geo.offsetY)
    }

    @Test
    fun `square source fills the whole target`() {
        val geo = PreprocessMath.letterboxGeometry(500, 500, 224)
        assertEquals(224, geo.innerWidth)
        assertEquals(224, geo.innerHeight)
        assertEquals(0, geo.offsetX)
        assertEquals(0, geo.offsetY)
    }

    @Test
    fun `scaled dimensions use round half up`() {
        // 1000x333 -> scale=0.224 -> 224 x (333*0.224=74.592 -> 75)
        val geo = PreprocessMath.letterboxGeometry(1000, 333, 224)
        assertEquals(224, geo.innerWidth)
        assertEquals(75, geo.innerHeight)
    }

    @Test
    fun `odd remainder goes to right and bottom`() {
        // 余 1px 时偏移取 floor，余量落在右/下
        val geo = PreprocessMath.letterboxGeometry(1000, 199, 224)
        // 199*0.224 = 44.576 -> 45; offsetY=(224-45)/2=89 (余 1 在下)
        assertEquals(45, geo.innerHeight)
        assertEquals(89, geo.offsetY)
    }

    // ---- half-pixel 源坐标与双线性 ----

    @Test
    fun `half pixel coordinate matches contract formula`() {
        // source_x = (target_x + 0.5) * src/dst - 0.5
        assertEquals(0f, PreprocessMath.halfPixelSourceCoord(0, 224, 224), 1e-5f)
        assertEquals(223f, PreprocessMath.halfPixelSourceCoord(223, 224, 224), 1e-5f)
        // 缩放 2 倍：target 0 -> (0.5)*2-0.5 = 0.5
        assertEquals(0.5f, PreprocessMath.halfPixelSourceCoord(0, 112, 224), 1e-5f)
    }

    @Test
    fun `bilinear returns corner values at integer coordinates`() {
        assertEquals(10f, PreprocessMath.bilinearSample(10f, 20f, 30f, 40f, 0f, 0f), 1e-5f)
        assertEquals(20f, PreprocessMath.bilinearSample(10f, 20f, 30f, 40f, 1f, 0f), 1e-5f)
        assertEquals(30f, PreprocessMath.bilinearSample(10f, 20f, 30f, 40f, 0f, 1f), 1e-5f)
        assertEquals(40f, PreprocessMath.bilinearSample(10f, 20f, 30f, 40f, 1f, 1f), 1e-5f)
    }

    @Test
    fun `bilinear midpoint is average and keeps float precision`() {
        assertEquals(15.5f, PreprocessMath.bilinearSample(10f, 21f, 10f, 21f, 0.5f, 0.5f), 1e-5f)
        // 小数权重：结果保留小数，不取整为 uint8
        // 10*.75*.25 + 21*.25*.25 + 20*.75*.75 + 31*.25*.75 = 20.25
        assertEquals(20.25f, PreprocessMath.bilinearSample(10f, 21f, 20f, 31f, 0.25f, 0.75f), 1e-5f)
    }

    // ---- 归一化约定 ----

    @Test
    fun `inside model normalization maps to identity`() {
        val preset = PreprocessMath.NormalizationPreset.fromName("inside model: x / 127.5 - 1")
        assertEquals(PreprocessMath.NormalizationPreset.IDENTITY, preset)
        assertEquals(0f, preset.apply(0f), 0f)
        assertEquals(255f, preset.apply(255f), 0f)
    }

    @Test
    fun `missing normalization defaults to identity per contract`() {
        assertEquals(PreprocessMath.NormalizationPreset.IDENTITY, PreprocessMath.NormalizationPreset.fromName(null))
        assertEquals(PreprocessMath.NormalizationPreset.IDENTITY, PreprocessMath.NormalizationPreset.fromName(""))
    }

    @Test
    fun `legacy presets still parse for old placeholder packages`() {
        assertEquals(
            PreprocessMath.NormalizationPreset.MOBILENET_V2_MINUS1_1,
            PreprocessMath.NormalizationPreset.fromName("mobilenet_v2_minus1_1"),
        )
        assertEquals(
            PreprocessMath.NormalizationPreset.UNIT_0_1,
            PreprocessMath.NormalizationPreset.fromName("unit_0_1"),
        )
    }

    @Test
    fun `unknown normalization name is rejected with actionable message`() {
        val error = runCatching {
            PreprocessMath.NormalizationPreset.fromName("client: x / 255")
        }.exceptionOrNull()
        assertTrue(error is IllegalArgumentException)
        assertTrue(error!!.message!!.contains("inside model"))
    }

    @Test
    fun `reference order bilinear stays within neighbour range over weight grid`() {
        // 修复前四项求和顺序会让全 255 邻域在部分权重下产出 255.00003（越界、被校验器拒绝）
        var fx = 0f
        while (fx <= 1f) {
            var fy = 0f
            while (fy <= 1f) {
                val v = PreprocessMath.bilinearSample(255f, 255f, 255f, 255f, fx, fy)
                assertTrue("fx=$fx fy=$fy v=$v", v <= 255f)
                val low = PreprocessMath.bilinearSample(0f, 0f, 0f, 0f, fx, fy)
                assertTrue("fx=$fx fy=$fy v=$low", low >= 0f)
                fy += 0.1f
            }
            fx += 0.1f
        }
    }

    @Test
    fun `clampPixel enforces contract range`() {
        assertEquals(255f, PreprocessMath.clampPixel(255.00003f), 0f)
        assertEquals(0f, PreprocessMath.clampPixel(-0.00003f), 0f)
        assertEquals(128f, PreprocessMath.clampPixel(128f), 0f)
        assertEquals(254.9f, PreprocessMath.clampPixel(254.9f), 0f)
    }

    @Test
    fun `identity preset preserves raw pixel values`() {
        val preset = PreprocessMath.NormalizationPreset.IDENTITY
        assertEquals(128f, preset.apply(PreprocessMath.PAD_VALUE), 0f)
        assertEquals(200f, preset.apply(200f), 0f)
    }
}