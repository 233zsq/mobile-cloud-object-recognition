package com.mobilecloud.recognition.inference

/**
 * 模型包校验结果。
 * 纯函数实现（不依赖 Android 与 LiteRT 类型），形状与 dtype 以字符串编码传入，便于单元测试。
 */
object ModelValidator {

    /** dtype 编码：float32 为基线；量化模型按契约需另行适配输入输出编码 */
    const val DTYPE_FLOAT32 = "float32"

    fun validate(
        inputShape: IntArray,
        inputDtype: String,
        outputShape: IntArray,
        labels: List<String>,
        metadata: ModelMetadata,
    ): List<String> {
        val errors = mutableListOf<String>()

        if (inputShape.size != 4) {
            errors.add("输入张量必须是4维 NCHW/NHWC，实际维度 ${inputShape.size}（${inputShape.joinToString(",")}）")
        } else {
            if (inputShape[0] != 1) errors.add("输入批大小必须是1，实际 ${inputShape[0]}")
            if (inputShape[1] != inputShape[2]) {
                errors.add("输入必须是正方形（中心裁剪假设），实际 ${inputShape[1]}x${inputShape[2]}")
            }
            if (inputShape[3] != 3) errors.add("输入通道数必须是3（RGB），实际 ${inputShape[3]}")
        }

        if (inputDtype != DTYPE_FLOAT32) {
            errors.add("当前版本仅支持 float32 输入；该模型输入为 $inputDtype，按 docs/model-contract.md 量化约定另行适配")
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

        return errors
    }
}
