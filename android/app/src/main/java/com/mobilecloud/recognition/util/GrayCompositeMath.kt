package com.mobilecloud.recognition.util

/**
 * 透明图灰色背景合成（纯整数运算，便于单测）。
 * 与 Python 参考实现（PIL `Image.alpha_composite`）逐值一致：四舍五入 `(fg*a + bg*(255-a) + 127) / 255`。
 * 向下截断会在半透明像素上与参考输入相差 1，超过端云同图对照 0.001 的约定误差（PR 审查修复项）。
 */
object GrayCompositeMath {

    const val BACKGROUND = 128

    fun composite(fg: Int, alpha: Int, background: Int = BACKGROUND): Int {
        require(fg in 0..255 && alpha in 0..255 && background in 0..255) {
            "通道值必须在 0-255：fg=$fg alpha=$alpha bg=$background"
        }
        return (fg * alpha + background * (255 - alpha) + 127) / 255
    }
}