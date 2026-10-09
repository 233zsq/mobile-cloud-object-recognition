package com.mobilecloud.recognition.inference

import com.mobilecloud.recognition.util.PreprocessMath

/**
 * 模型包校验结果。
 * 纯函数实现（不依赖 Android 与 LiteRT 类型），形状与 dtype 以字符串编码传入，便于单元测试。
 * 校验不通过时上层必须停止识别并给出原因，不得输出伪造分类结果（用例 T04）。
 */
object ModelValidator {

    /** dtype 编码：契约 rgb-letterbox-v1 固定 float32；量化模型按契约另行适配 */
    const val DTYPE_FLOAT32 = "float32"

    /** 契约要求的像素范围 */
    private val REQUIRED_PIXEL_RANGE = listOf(0, 255)

    fun validate(
        inputShape: IntArray,
        inputDtype: String,
        outputShape: IntArray,
        labels: List<String>,
        metadata: ModelMetadata,
    ): List<String> {
        val errors = mutableListOf<String>()

        if (inputShape.size != 4) {
            errors.add("输入张量必须是4维 NHWC，实际维度 ${inputShape.size}（${inputShape.joinToString(",")}）")
        } else {
            if (inputShape[0] != 1) errors.add("输入批大小必须是1，实际 ${inputShape[0]}")
            if (inputShape[1] != inputShape[2]) {
                errors.add("输入必须是正方形（契约 letterbox 目标），实际 ${inputShape[1]}x${inputShape[2]}")
            }
            if (inputShape[3] != 3) errors.add("输入通道数必须是3（RGB），实际 ${inputShape[3]}")
        }

        if (inputDtype != DTYPE_FLOAT32) {
            errors.add("契约 rgb-letterbox-v1 仅支持 float32 输入；该模型输入为 $inputDtype")
        }

        if (outputShape.size != 2) {
            errors.add("输出张量必须是2维 [1,类别数]，实际维度 ${outputShape.size}（${outputShape.joinToString(",")}）")
        } else if (outputShape[0] != 1) {
            errors.add("输出批大小必须是1，实际 ${outputShape[0]}")
        }

        if (labels.isEmpty()) errors.add("labels.txt 为空")

        if (inputShape.size == 4 && outputShape.size == 2 && labels.isNotEmpty()) {
            if (outputShape.last() != labels.size) {
                errors.add("标签行数(${labels.size})与模型输出维度(${outputShape.last()})不一致，核对 labels.txt 顺序")
            }
        }

        if (metadata.modelVersion.isNullOrBlank()) {
            errors.add("metadata.json 缺少 model_version，拒绝加载无版本模型")
        }

        // 契约：输入为 0–255 原始像素，归一化在模型内部完成
        metadata.input.pixelRange?.let { range ->
            if (range != REQUIRED_PIXEL_RANGE) {
                errors.add("input.pixel_range 契约要求 [0,255]，实际 $range")
            }
        }
        runCatching { PreprocessMath.NormalizationPreset.fromName(metadata.input.normalization) }
            .onFailure { errors.add(it.message ?: "归一化约定无法解析") }

        // metadata 声明的形状必须与实际张量一致，防止标签/形状混用旧版本
        metadata.input.shapeArray?.let { declared ->
            if (!declared.contentEquals(inputShape)) {
                errors.add("metadata input.shape (${declared.joinToString(",")}) 与实际输入张量 (${inputShape.joinToString(",")}) 不一致")
            }
        }
        metadata.output.shapeArray?.let { declared ->
            if (!declared.contentEquals(outputShape)) {
                errors.add("metadata output.shape (${declared.joinToString(",")}) 与实际输出张量 (${outputShape.joinToString(",")}) 不一致")
            }
        }

        return errors
    }
}