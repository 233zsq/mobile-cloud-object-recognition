package com.mobilecloud.recognition.ui.records

/**
 * 删除记录的提示文案（纯函数，便于单测）。
 * 删除只作用于本机：后端没有删除接口，已入库记录在云端仍然保留，必须在确认框里说清楚。
 */
object RecordDeletionText {

    fun confirm(pendingSync: Boolean, corrected: Boolean): String = buildString {
        append("将删除本机记录与照片文件，无法恢复。")
        if (pendingSync) {
            append("该记录尚未同步到云端，删除后不会再上传。")
        } else {
            append("该记录已同步到云端，删除只影响本机展示，云端数据仍然保留。")
        }
        if (corrected) {
            append("人工修正记录会一并删除。")
        }
    }

    fun result(uploaded: Boolean): String = if (uploaded) {
        "已删除本地记录；云端已入库的数据未受影响"
    } else {
        "已删除未同步的本地记录"
    }

    /** 清空全部：确认框文案（总数、未同步数、云端保留说明） */
    fun clearConfirm(total: Int, pending: Int): String = buildString {
        append("将删除本机全部 $total 条识别记录及照片文件，无法恢复。")
        if (pending > 0) {
            append("其中 $pending 条尚未同步到云端，删除后不会再上传。")
        }
        val uploaded = total - pending
        if (uploaded > 0) {
            append("已同步到云端的 $uploaded 条记录在服务端仍然保留。")
        }
    }

    /** 清空全部：结果提示 */
    fun clearResult(total: Int, pending: Int): String = buildString {
        append("已清空 $total 条本地记录")
        if (pending > 0) {
            append("（其中 $pending 条未同步，已放弃上传）")
        }
    }
}