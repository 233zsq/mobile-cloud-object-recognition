package com.mobilecloud.recognition.util

/**
 * 图像几何与数值预处理的纯函数集合，不依赖 Android 类，便于单元测试。
 * 预处理约定与 docs/model-contract.md 保持一致：中心裁剪、缩放到模型输入边长、按预设归一化。
 */
object PreprocessMath {

    /** EXIF 方向常量（与 JPEG EXIF 规范一致，取值与 androidx ExifInterface 相同） */
    const val EXIF_NORMAL = 1
    const val EXIF_ROTATE_180 = 3
    const val EXIF_ROTATE_90 = 6
    const val EXIF_ROTATE_270 = 8
    const val EXIF_FLIP_HORIZONTAL = 2
    const val EXIF_FLIP_VERTICAL = 4
    const val EXIF_TRANSPOSE = 5
    const val EXIF_TRANSVERSE = 7

    data class ImageTransform(val degrees: Int, val flipHorizontal: Boolean, val flipVertical: Boolean)

    fun transformForExif(exifOrientation: Int): ImageTransform = when (exifOrientation) {
        EXIF_ROTATE_90 -> ImageTransform(90, false, false)
        EXIF_ROTATE_180 -> ImageTransform(180, false, false)
        EXIF_ROTATE_270 -> ImageTransform(270, false, false)
        EXIF_FLIP_HORIZONTAL -> ImageTransform(0, true, false)
        EXIF_FLIP_VERTICAL -> ImageTransform(180, true, false)
        EXIF_TRANSPOSE -> ImageTransform(90, true, false)
        EXIF_TRANSVERSE -> ImageTransform(270, true, false)
        else -> ImageTransform(0, false, false)
    }

    /** 在源图上取尽可能大的居中正方形裁剪区域 */
    data class CropSpec(val left: Int, val top: Int, val size: Int)

    fun centerCropSpec(srcWidth: Int, srcHeight: Int): CropSpec {
        require(srcWidth > 0 && srcHeight > 0) { "图片尺寸必须为正，实际 ${srcWidth}x$srcHeight" }
        val side = minOf(srcWidth, srcHeight)
        return CropSpec((srcWidth - side) / 2, (srcHeight - side) / 2, side)
    }

    /**
     * 归一化预设，名称与模型包 metadata.json 的 input.normalization 字段对应。
     * MOBILENET_V2_MINUS1_1：x/127.5 - 1，映射到 [-1, 1]（MobileNetV2 迁移学习基线）。
     * UNIT_0_1：x/255，映射到 [0, 1]。
     */
    enum class NormalizationPreset(val apply: (Int) -> Float) {
        MOBILENET_V2_MINUS1_1({ it / 127.5f - 1f }),
        UNIT_0_1({ it / 255f });

        companion object {
            fun fromName(name: String?): NormalizationPreset = when (name?.trim()?.lowercase()) {
                null, "", "mobilenet_v2_minus1_1" -> MOBILENET_V2_MINUS1_1
                "unit_0_1" -> UNIT_0_1
                else -> throw IllegalArgumentException("未知的归一化预设: $name，核对 metadata.json 的 input.normalization")
            }
        }
    }

    /** 解析 metadata 中 "1,224,224,3" 形式的形状字符串 */
    fun parseShape(text: String?): IntArray? = text
        ?.split(',', 'x', 'X', '×')
        ?.mapNotNull { it.trim().toIntOrNull() }
        ?.takeIf { it.isNotEmpty() }
        ?.toIntArray()
}
