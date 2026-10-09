package com.mobilecloud.recognition.camera

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import com.mobilecloud.recognition.util.GrayCompositeMath
import com.mobilecloud.recognition.util.PreprocessMath
import java.io.File
import java.util.UUID

/**
 * 照片本地管理：保存到应用私有目录（无需存储权限），解码时按 EXIF 旋转为直立图（用例 T02）。
 * 提供 internal 级辅助函数供端云一致性自检复用（示例图片从 assets 解码走同一套方向与灰底规则）。
 */
class PhotoStore(private val context: Context) {

    private val photoDir = File(context.filesDir, "photos")

    fun newPhotoFile(): File {
        photoDir.mkdirs()
        return File(photoDir, "${UUID.randomUUID()}.jpg")
    }

    /**
     * 把相册/文件选择器返回的图片复制进应用私有目录，供识别与记录使用。
     * 按字节复制以保留 EXIF 方向信息（重新编码会丢失 EXIF，破坏方向处理契约）；
     * 复制后校验可解码，避免把非图片或损坏文件写入记录。
     */
    fun importToPrivateStorage(uri: android.net.Uri): File {
        val target = newPhotoFile()
        try {
            val input = context.contentResolver.openInputStream(uri)
                ?: throw IllegalStateException("无法读取所选图片")
            input.use { source ->
                target.outputStream().use { destination -> source.copyTo(destination) }
            }
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(target.absolutePath, bounds)
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
                throw IllegalStateException("所选文件不是可识别的图片")
            }
            return target
        } catch (e: Exception) {
            target.delete()
            throw e
        }
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
        val orientation = readExifOrientation(file)
        val upright = applyExifOrientation(decoded, orientation)
        return compositeTransparencyOnGray(upright)
    }

    companion object {
        /** EXIF 方向常量，测试与文档引用 */
        val ORIENTATION_NORMAL = PreprocessMath.EXIF_NORMAL
    }
}

/** 从 assets 解码图片并按契约应用 EXIF 方向与灰底合成（端云一致性自检使用） */
internal fun decodeAssetUpright(context: Context, assetPath: String): Bitmap? {
    val assets = context.assets
    val options = BitmapFactory.Options().apply { inPreferredConfig = Bitmap.Config.ARGB_8888 }
    val decoded = assets.open(assetPath).use { input ->
        BitmapFactory.decodeStream(input, null, options)
    } ?: return null
    val orientation = try {
        assets.open(assetPath).use { input ->
            ExifInterface(input).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        }
    } catch (_: Exception) {
        ExifInterface.ORIENTATION_NORMAL
    }
    val upright = applyExifOrientation(decoded, orientation)
    return compositeTransparencyOnGray(upright)
}

private fun readExifOrientation(file: File): Int = try {
    ExifInterface(file.absolutePath)
        .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
} catch (_: Exception) {
    ExifInterface.ORIENTATION_NORMAL
}

internal fun applyExifOrientation(bitmap: Bitmap, orientation: Int): Bitmap {
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

/** 契约：透明图片先在灰色(128)背景合成，再进入 letterbox 预处理 */
internal fun compositeTransparencyOnGray(bitmap: Bitmap): Bitmap {
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
        // 与 Python 参考实现（PIL Image.alpha_composite）一致的四舍五入口径，见 GrayCompositeMath
        val r = GrayCompositeMath.composite((pixel shr 16) and 0xFF, alpha)
        val g = GrayCompositeMath.composite((pixel shr 8) and 0xFF, alpha)
        val b = GrayCompositeMath.composite(pixel and 0xFF, alpha)
        pixels[i] = (0xFF shl 24) or (r shl 16) or (g shl 8) or b
    }
    val composed = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
    composed.setPixels(pixels, 0, width, 0, 0, width, height)
    if (composed != bitmap) bitmap.recycle()
    return composed
}