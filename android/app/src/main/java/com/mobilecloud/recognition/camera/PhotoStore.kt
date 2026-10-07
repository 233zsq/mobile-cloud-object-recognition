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

    /** 解码为直立图（已应用 EXIF 方向），最长边限制在 [maxDimension] 内以控制内存 */
    fun decodeUpright(file: File, maxDimension: Int = 2048): Bitmap? {
        if (!file.exists()) return null

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

        var sample = 1
        var maxSide = maxOf(bounds.outWidth, bounds.outHeight)
        while (maxSide / (sample * 2) >= maxDimension / 2) sample *= 2

        val options = BitmapFactory.Options().apply {
            inSampleSize = sample
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val decoded = BitmapFactory.decodeFile(file.absolutePath, options) ?: return null
        return applyExifOrientation(decoded, file)
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
