package com.mobilecloud.recognition.util

import java.io.ByteArrayOutputStream

/**
 * 解码前剥离颜色管理元数据，使 Android 解码结果与参考实现逐像素一致。
 *
 * 背景（真机联调实测）：契约 rgb-letterbox-v1 的像素定义以 `ml/src/recognition/preprocessing.py`
 * （PIL，**不做颜色管理**）为准；而 Android/Skia 解码会应用嵌入的颜色信息——
 * PNG 的 gAMA/cHRM 与 JPEG 的 ICC 配置（实测样例含 Adobe RGB 1998，
 * 应用后与参考输入相差最大 17/255，超出 0.001 的对照阈值）。
 * BitmapFactory/ImageDecoder 没有关闭颜色管理的开关，因此在把字节交给解码器之前
 * 移除这些元数据：PNG 去掉 gAMA/cHRM/iCCP/sRGB 块，JPEG 去掉 APP2 的 ICC_PROFILE 段。
 *
 * 仅做无损的段/块删除：JPEG 的 EXIF（APP1，方向信息）与 PNG 的其余块原样保留。
 * 非 JPEG/PNG 或结构异常时原样返回（不在解码前抛错，交由解码器报告）。
 */
object ImageMetadataStripper {

    private val PNG_SIGNATURE = byteArrayOf(
        0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
    )
    private val ICC_SIGNATURE = "ICC_PROFILE\u0000".toByteArray(Charsets.US_ASCII)
    private val PNG_COLOR_CHUNKS = setOf("gAMA", "cHRM", "iCCP", "sRGB")

    fun stripColorManagement(bytes: ByteArray): ByteArray = when {
        isJpeg(bytes) -> stripJpegIcc(bytes)
        isPng(bytes) -> stripPngColorChunks(bytes)
        else -> bytes
    }

    private fun isJpeg(bytes: ByteArray): Boolean =
        bytes.size > 3 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte()

    private fun isPng(bytes: ByteArray): Boolean =
        bytes.size > PNG_SIGNATURE.size &&
            PNG_SIGNATURE.indices.all { bytes[it] == PNG_SIGNATURE[it] }

    private fun stripJpegIcc(bytes: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(bytes.size)
        out.write(bytes, 0, 2) // SOI
        var i = 2
        while (i + 3 < bytes.size) {
            if (bytes[i] != 0xFF.toByte()) return bytes // 结构异常，保守原样返回
            val marker = bytes[i + 1].toInt() and 0xFF
            if (marker == 0xDA) { // SOS 及其后的熵编码数据原样保留
                out.write(bytes, i, bytes.size - i)
                return out.toByteArray()
            }
            if (marker == 0x01 || marker in 0xD0..0xD7) { // 无长度字段的标记
                out.write(bytes, i, 2)
                i += 2
                continue
            }
            val length = ((bytes[i + 2].toInt() and 0xFF) shl 8) or (bytes[i + 3].toInt() and 0xFF)
            if (length < 2 || i + 2 + length > bytes.size) return bytes
            val isIcc = marker == 0xE2 && hasIccSignature(bytes, i + 4, length - 2)
            if (!isIcc) out.write(bytes, i, 2 + length)
            i += 2 + length
        }
        return bytes // 未遇到 SOS：保守原样返回
    }

    private fun hasIccSignature(bytes: ByteArray, offset: Int, payloadLength: Int): Boolean {
        if (payloadLength < ICC_SIGNATURE.size) return false
        return ICC_SIGNATURE.indices.all { bytes[offset + it] == ICC_SIGNATURE[it] }
    }

    private fun stripPngColorChunks(bytes: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(bytes.size)
        out.write(bytes, 0, PNG_SIGNATURE.size)
        var i = PNG_SIGNATURE.size
        var reachedEnd = false
        while (i + 12 <= bytes.size) {
            val length = ((bytes[i].toInt() and 0xFF) shl 24) or
                ((bytes[i + 1].toInt() and 0xFF) shl 16) or
                ((bytes[i + 2].toInt() and 0xFF) shl 8) or
                (bytes[i + 3].toInt() and 0xFF)
            if (length < 0 || i + 12 + length > bytes.size) return bytes // 结构异常，原样返回
            val type = String(bytes, i + 4, 4, Charsets.US_ASCII)
            if (type !in PNG_COLOR_CHUNKS) out.write(bytes, i, 12 + length)
            i += 12 + length
            if (type == "IEND") {
                reachedEnd = true
                break
            }
        }
        // 未读到 IEND（截断文件）：保守原样返回，不把残缺数据交给解码器
        if (!reachedEnd) return bytes
        if (i < bytes.size) out.write(bytes, i, bytes.size - i) // IEND 之后的残余字节也保留
        return out.toByteArray()
    }
}