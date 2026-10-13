package com.mobilecloud.recognition.camera

import android.graphics.Bitmap
import android.graphics.Matrix
import androidx.camera.core.ImageProxy

/** Convert the shared CameraX viewport crop to an upright RGB bitmap, before normal letterboxing. */
object PreviewFrameBitmap {
    fun upright(image: ImageProxy): Bitmap {
        val full = image.toBitmap()
        try {
            val crop = image.cropRect
            require(crop.width() > 0 && crop.height() > 0) { "相机画面为空" }
            val rotation = image.imageInfo.rotationDegrees
            val matrix = Matrix().apply { postRotate(rotation.toFloat()) }
            val upright = Bitmap.createBitmap(full, crop.left, crop.top, crop.width(), crop.height(), matrix, true)
            if (upright !== full) full.recycle()
            return upright
        } catch (error: Throwable) {
            full.recycle()
            throw error
        }
    }
}
