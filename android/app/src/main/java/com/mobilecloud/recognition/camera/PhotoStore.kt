package com.mobilecloud.recognition.camera

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import com.mobilecloud.recognition.util.PreprocessMath
import java.io.File
import java.util.UUID

/**
 * 照片本地管理：保存到应用私有目录（无需存储权限），解码时按 EXIF 旋转为直立图（用例 T02）。
 */
class PhotoStore(context: Context) {

    private val photoDir = File(context.filesDir, "photos")

    fun newPhotoFile(): File {
        photoDir.mkdirs()
        return File(photoDir, "${UUID.randomUUID()}.jpg")
    }

    /**
     * 解码为直立图（已应用 EXIF 方向）。
     * [maxDimension] 为 null 时保持原始分辨率——推理路径必须使用原图，
     * 下采样会改变 letterbox 双线性插值结果，破坏端云同图一致性（契约 rgb-letterbox-v1）；
     * 缩略图等展示用途传入目标尺寸以限制内存。
     */
    fun decodeUpright(file: File, maxDimension: Int? = null): Bitmap? {
        if (!file.exists()) return null

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

        var sample = 1
        if (maxDimension != null && maxDimension > 0) {
            var maxSide = maxOf(bounds.outWidth, bounds.outHeight)
            while (maxSide / (sample * 2) >= maxDimension / 2) sample *= 2
        }

        val options = BitmapFactory.Options().apply {
            inSampleSize = sample
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val decoded = BitmapFactory.decodeFile(file.absolutePath, options) ?: return null
        val upright = applyExifOrientation(decoded, file)
        return compositeTransparencyOnGray(upright)
    }

    /** 契约：透明图片先在灰色(128)背景合成，再进入 letterbox 预处理 */
    private fun compositeTransparencyOnGray(bitmap: Bitmap): Bitmap {
        if (!bitmap.hasAlpha()) return bitmap
        val width = bitmap.width
        val height = bitmap.height
        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
        var hasTransparency = false
        for (pixel in pixels) {
            val alpha = (pixel ushr 24) and 0xFF
            if (alpha != 0xFF) {
                hasTransparency = true
                break
            }
        }
        if (!hasTransparency) return bitmap

        for (i in pixels.indices) {
            val pixel = pixels[i]
            val alpha = (pixel ushr 24) and 0xFF
            if (alpha == 0xFF) continue
            val ratio = alpha / 255f
            val r = (((pixel shr 16) and 0xFF) * ratio + 128f * (1f - ratio)).toInt()
            val g = (((pixel shr 8) and 0xFF) * ratio + 128f * (1f - ratio)).toInt()
            val b = ((pixel and 0xFF) * ratio + 128f * (1f - ratio)).toInt()
            pixels[i] = (0xFF shl 24) or (r shl 16) or (g shl 8) or b
        }
        val composed = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        composed.setPixels(pixels, 0, width, 0, 0, width, height)
        if (composed != bitmap) bitmap.recycle()
        return composed
    }

    private fun applyExifOrientation(bitmap: Bitmap, file: File): Bitmap {
        val orientation = try {
            ExifInterface(file.absolutePath)
                .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        } catch (_: Exception) {
            ExifInterface.ORIENTATION_NORMAL
        }
        val transform = PreprocessMath.transformForExif(orientation)
        if (transform.degrees == 0 && !transform.flipHorizontal && !transform.flipVertical) {
            return bitmap
        }
        val matrix = Matrix().apply {
            postRotate(transform.degrees.toFloat())
            if (transform.flipHorizontal) postScale(-1f, 1f, bitmap.width / 2f, bitmap.height / 2f)
            if (transform.flipVertical) postScale(1f, -1f, bitmap.width / 2f, bitmap.height / 2f)
        }
        val rotated = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        if (rotated != bitmap) bitmap.recycle()
        return rotated
    }

    companion object {
        /** EXIF 方向常量，测试与文档引用 */
        val ORIENTATION_NORMAL = PreprocessMath.EXIF_NORMAL
    }
}
