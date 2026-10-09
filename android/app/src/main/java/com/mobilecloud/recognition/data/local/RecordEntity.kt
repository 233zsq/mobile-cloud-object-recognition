package com.mobilecloud.recognition.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * 一条识别记录。recordId 在手机端生成后永不变更，上报与补传使用同一 UUID（F04/T07/T08）。
 * 原始预测（predicted*）只写入一次；人工纠错写到 corrected* 并递增 revision，不覆盖原预测（F03/T10）。
 */
@Entity(tableName = "records")
data class RecordEntity(
    @PrimaryKey val recordId: String,
    val clientId: String,
    val modelVersion: String,
    /** 模型输出索引（=类别 ID），原预测 */
    val predictedIndex: Int,
    /** 原预测标签（labels.txt 对应行） */
    val predictedLabel: String,
    val confidence: Float,
    /** 预处理+推理总耗时（毫秒） */
    val latencyMs: Long,
    /** 采集时间（epoch 毫秒） */
    val capturedAt: Long,
    val photoPath: String? = null,
    /** 人工纠错的类别 ID，null 表示未纠错 */
    val correctedIndex: Int? = null,
    val correctedLabel: String? = null,
    /** 修订号：从 0 开始，每次纠错 +1；后端据此拒绝过期请求（T11） */
    val revision: Int = 0,
    val correctedAt: Long? = null,
    /** 原始预测上报状态 */
    val uploaded: Boolean = false,
    /** 纠错修订是否待同步 */
    val correctionPending: Boolean = false,
    /** 最近一次同步失败的说明，展示用 */
    val lastError: String? = null,
    val updatedAt: Long,
) {
    val pendingSync: Boolean
        get() = !uploaded || correctionPending

    /** 界面展示用的当前类别标签：人工纠错优先，原预测兜底 */
    val displayLabel: String
        get() = correctedLabel ?: predictedLabel
}
