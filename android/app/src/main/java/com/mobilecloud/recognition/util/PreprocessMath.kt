package com.mobilecloud.recognition.util

/**
 * 预处理纯函数集合，实现契约 `rgb-letterbox-v1`（docs/model-contract.md、docs/ml-handover.md）。
 * 不依赖 Android 类，便于单元测试；几何与归一化约定必须与云端/PC 参考实现逐字一致。
 *
 * 契约要点：
 * - EXIF 纠正方向后等比缩放，双线性、half-pixel 坐标、不额外抗锯齿；
 * - 缩放宽高 `floor(原尺寸 * scale + 0.5)`，`scale = 目标边长 / max(原宽, 原高)`；
 * - 灰色 128 居中补边，不裁剪，奇数余量位于右/下；
 * - 四邻域加权结果保留 float32，不先取整为 uint8；
 * - 归一化在模型内部完成，端侧直送 0–255 原始像素。
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

    /** 契约：灰色补边值 */
    const val PAD_VALUE = 128f

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

    /**
     * 等比缩放后的内框尺寸与居中偏移。
     * 契约：`scale = target / max(srcW, srcH)`，宽高 `floor(原尺寸 * scale + 0.5)`（round half up）。
     */
    data class LetterboxGeometry(
        val innerWidth: Int,
        val innerHeight: Int,
        val offsetX: Int,
        val offsetY: Int,
    )

    fun letterboxGeometry(srcWidth: Int, srcHeight: Int, target: Int): LetterboxGeometry {
        require(srcWidth > 0 && srcHeight > 0) { "图片尺寸必须为正，实际 ${srcWidth}x$srcHeight" }
        require(target > 0) { "目标边长必须为正，实际 $target" }
        val scale = target.toDouble() / maxOf(srcWidth, srcHeight)
        val innerWidth = maxOf(1, floorToInt(srcWidth * scale + 0.5)).coerceAtMost(target)
        val innerHeight = maxOf(1, floorToInt(srcHeight * scale + 0.5)).coerceAtMost(target)
        // 居中；奇数余量在右/下，因此偏移取 floor（余下 1px 落到右/下）
        return LetterboxGeometry(
            innerWidth = innerWidth,
            innerHeight = innerHeight,
            offsetX = (target - innerWidth) / 2,
            offsetY = (target - innerHeight) / 2,
        )
    }

    /** half-pixel 源坐标：contract `source_x = (target_x + 0.5) * source_width / target_width - 0.5` */
    fun halfPixelSourceCoord(dstIndex: Int, dstSize: Int, srcSize: Int): Float =
        ((dstIndex + 0.5f) * srcSize / dstSize) - 0.5f

    /**
     * 四邻域双线性加权，0–255 float 空间直接计算，不取整为整数。
     * 求值顺序与 Python 参考实现（`recognition.preprocessing.bilinear`）一致：
     * 先水平两段、再垂直混合——顺序不同会造成舍入方向不同，
     * 曾导致输出越过 255 上界、被端云一致性校验器拒绝（PR 联调修复项）。
     */
    fun bilinearSample(v00: Float, v10: Float, v01: Float, v11: Float, fx: Float, fy: Float): Float {
        val top = v00 * (1f - fx) + v10 * fx
        val bottom = v01 * (1f - fx) + v11 * fx
        return top * (1f - fy) + bottom * fy
    }

    /**
     * 契约要求输入像素在 0–255。浮点舍入可能产生 ±1 ulp 的越界（如 255.00003），
     * 写输入缓冲前收敛到合法范围；钳制量 ≤1e-5，远低于端云对照 0.001 的阈值。
     */
    fun clampPixel(value: Float): Float = value.coerceIn(0f, 255f)

    private fun floorToInt(value: Double): Int = kotlin.math.floor(value).toInt()

    /**
     * 归一化预设。契约 rgb-letterbox-v1 的模型把 `x / 127.5 - 1` 做在模型内部，
     * 端侧必须使用 [IDENTITY] 直送 0–255 原始像素（重复归一化会被参考张量对照检出）。
     */
    enum class NormalizationPreset(val apply: (Float) -> Float) {
        /** 契约路径：端侧不做任何归一化 */
        IDENTITY({ it }),
        UNIT_0_1({ it / 255f }),

        /** 历史占位模型的端侧归一化，仅用于兼容旧包；正式契约禁用 */
        MOBILENET_V2_MINUS1_1({ it / 127.5f - 1f });

        companion object {
            fun fromName(name: String?): NormalizationPreset {
                val value = name?.trim()?.lowercase()
                return when {
                    value.isNullOrEmpty() -> IDENTITY
                    value.startsWith("inside model") -> IDENTITY
                    value == "identity" || value == "none" -> IDENTITY
                    value == "unit_0_1" -> UNIT_0_1
                    value == "mobilenet_v2_minus1_1" -> MOBILENET_V2_MINUS1_1
                    else -> throw IllegalArgumentException(
                        "未知的归一化约定「$name」；契约 rgb-letterbox-v1 要求 " +
                            "\"inside model: x / 127.5 - 1\"，端侧使用恒等（原始 0–255）",
                    )
                }
            }
        }
    }
}