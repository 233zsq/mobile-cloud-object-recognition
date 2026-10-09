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
}