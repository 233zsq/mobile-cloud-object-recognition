package com.mobilecloud.recognition

import com.mobilecloud.recognition.util.GrayCompositeMath
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 透明图灰色背景合成：期望值由 Python 参考实现（PIL Image.alpha_composite，
 * 灰色背景 128）逐值生成，半透明像素也须一致（PR 审查修复项）。
 */
class GrayCompositeMathTest {

    @Test
    fun `matches PIL alpha_composite for sampled foreground and alpha pairs`() {
        val expected = listOf(
            Triple(0, 0, 128), Triple(0, 1, 127), Triple(0, 34, 111), Triple(0, 128, 64),
            Triple(0, 254, 1), Triple(0, 255, 0), Triple(17, 17, 121), Triple(200, 128, 164),
            Triple(255, 1, 128), Triple(255, 128, 192), Triple(255, 254, 255), Triple(255, 255, 255),
            Triple(100, 200, 106), Triple(50, 50, 113),
        )
        for ((fg, alpha, want) in expected) {
            assertEquals("fg=$fg alpha=$alpha", want, GrayCompositeMath.composite(fg, alpha))
        }
    }

    @Test
    fun `fully transparent pixel becomes background`() {
        assertEquals(128, GrayCompositeMath.composite(0, 0))
        assertEquals(128, GrayCompositeMath.composite(255, 0))
    }

    @Test
    fun `opaque pixel keeps its value`() {
        assertEquals(0, GrayCompositeMath.composite(0, 255))
        assertEquals(255, GrayCompositeMath.composite(255, 255))
        assertEquals(123, GrayCompositeMath.composite(123, 255))
    }

    @Test
    fun `rounding is not truncation`() {
        // 反例：向下截断会给 110/93/76，四舍五入为 111/94/77
        assertEquals(111, GrayCompositeMath.composite(0, 34))
        assertEquals(94, GrayCompositeMath.composite(0, 68))
        assertEquals(77, GrayCompositeMath.composite(0, 102))
    }
}