package com.mobilecloud.recognition

import com.mobilecloud.recognition.util.ImageMetadataStripper
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 颜色管理元数据剥离：Android/Skia 会应用 PNG 的 gAMA/cHRM 与 JPEG 的 ICC，
 * 参考实现（PIL）不会，导致端云同图对照失败。剥离后交给解码器即可一致。
 */
class ImageMetadataStripperTest {

    // ---- JPEG ----

    /** 组装最小 JPEG 片段：SOI + 若干段 + SOS + 扫描数据 */
    private fun jpeg(vararg segments: ByteArray): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        out.write(byteArrayOf(0xFF.toByte(), 0xD8.toByte()))
        segments.forEach { out.write(it) }
        return out.toByteArray()
    }

    private fun segment(marker: Int, payload: ByteArray): ByteArray {
        val length = payload.size + 2
        val head = byteArrayOf(0xFF.toByte(), marker.toByte(), (length shr 8).toByte(), length.toByte())
        return head + payload
    }

    private val iccApp2 = segment(0xE2, "ICC_PROFILE\u0000".toByteArray(Charsets.US_ASCII) + ByteArray(64) { 7 })
    private val exifApp1 = segment(0xE1, "Exif\u0000\u0000".toByteArray(Charsets.US_ASCII) + ByteArray(32))
    private val sos = segment(0xDA, ByteArray(10) { 3 })
    private val scanData = ByteArray(20) { 1 }

    @Test
    fun `jpeg drops icc app2 and keeps exif and scan data`() {
        val source = jpeg(iccApp2, exifApp1, sos) + scanData
        val stripped = ImageMetadataStripper.stripColorManagement(source)
        assertTrue("SOI 保留", stripped[0] == 0xFF.toByte() && stripped[1] == 0xD8.toByte())
        assertTrue("ICC APP2 已移除", !contains(stripped, "ICC_PROFILE".toByteArray(Charsets.US_ASCII)))
        assertTrue("EXIF APP1 保留", contains(stripped, "Exif".toByteArray(Charsets.US_ASCII)))
        assertTrue("SOS 之后扫描数据完整保留", stripped.takeLast(scanData.size).toByteArray().contentEquals(scanData))
        assertTrue("长度缩短（恰好去掉 ICC 段）", stripped.size == source.size - iccApp2.size)
    }

    @Test
    fun `jpeg without icc is byte identical`() {
        val source = jpeg(exifApp1, sos) + scanData
        assertArrayEquals(source, ImageMetadataStripper.stripColorManagement(source))
    }

    @Test
    fun `non icc app2 is preserved`() {
        val otherApp2 = segment(0xE2, "MPF\u0000".toByteArray(Charsets.US_ASCII) + ByteArray(8))
        val source = jpeg(otherApp2, sos) + scanData
        assertArrayEquals(source, ImageMetadataStripper.stripColorManagement(source))
    }

    // ---- PNG ----

    private fun chunk(type: String, data: ByteArray): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val length = data.size
        out.write(byteArrayOf((length shr 24).toByte(), (length shr 16).toByte(), (length shr 8).toByte(), length.toByte()))
        out.write(type.toByteArray(Charsets.US_ASCII))
        out.write(data)
        out.write(byteArrayOf(0xDE.toByte(), 0xAD.toByte(), 0xBE.toByte(), 0xEF.toByte())) // 伪 CRC（不参与校验）
        return out.toByteArray()
    }

    private val pngSignature = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)

    @Test
    fun `png drops gamma chroma iccp and srgb chunks only`() {
        val ihdr = chunk("IHDR", ByteArray(13) { 1 })
        val gama = chunk("gAMA", byteArrayOf(0x00, 0x01, 0x86.toByte(), 0xA0.toByte()))
        val chrm = chunk("cHRM", ByteArray(32) { 2 })
        val iccp = chunk("iCCP", ByteArray(24) { 3 })
        val srgb = chunk("sRGB", ByteArray(1) { 4 })
        val idat = chunk("IDAT", ByteArray(64) { 5 })
        val iend = chunk("IEND", ByteArray(0))
        val source = pngSignature + ihdr + gama + chrm + iccp + srgb + idat + iend

        val stripped = ImageMetadataStripper.stripColorManagement(source)

        val expected = pngSignature + ihdr + idat + iend
        assertArrayEquals(expected, stripped)
        assertTrue("IHDR/IDAT 原样保留", contains(stripped, "IDAT".toByteArray(Charsets.US_ASCII)))
        assertTrue("sRGB 已移除", !contains(stripped, "sRGB".toByteArray(Charsets.US_ASCII)))
    }

    @Test
    fun `png without color chunks is byte identical`() {
        val ihdr = chunk("IHDR", ByteArray(13) { 1 })
        val idat = chunk("IDAT", ByteArray(8) { 2 })
        val iend = chunk("IEND", ByteArray(0))
        val source = pngSignature + ihdr + idat + iend
        assertArrayEquals(source, ImageMetadataStripper.stripColorManagement(source))
    }

    // ---- 其它 ----

    @Test
    fun `unknown and malformed inputs pass through unchanged`() {
        val text = "not an image".toByteArray()
        assertArrayEquals(text, ImageMetadataStripper.stripColorManagement(text))
        val truncatedJpeg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte())
        assertArrayEquals(truncatedJpeg, ImageMetadataStripper.stripColorManagement(truncatedJpeg))
        val badPngLength = pngSignature + byteArrayOf(0x7F, 0xFF.toByte(), 0xFF.toByte(), 0xFF.toByte(), 0x00, 0x00, 0x00, 0x00)
        assertArrayEquals(badPngLength, ImageMetadataStripper.stripColorManagement(badPngLength))
    }

    private fun contains(haystack: ByteArray, needle: ByteArray): Boolean {
        outer@ for (i in 0..haystack.size - needle.size) {
            for (j in needle.indices) if (haystack[i + j] != needle[j]) continue@outer
            return true
        }
        return false
    }
}