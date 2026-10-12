package com.mobilecloud.recognition.ui.records

import com.mobilecloud.recognition.data.local.RecordEntity

/** A single snapshot keeps visible counts and whole-device actions consistent. */
data class RecordSelection(
    val records: List<RecordEntity>,
    val modelVersions: List<String>,
    val modelVersion: String?,
    val allCount: Int,
    val allPendingCount: Int,
) {
    val count: Int get() = records.size
    val pendingCount: Int get() = records.count { it.pendingSync }
    val correctedCount: Int get() = records.count { it.correctedLabel != null }
}

fun selectRecords(records: List<RecordEntity>, modelVersion: String?): RecordSelection =
    RecordSelection(
        records = if (modelVersion == null) records else records.filter { it.modelVersion == modelVersion },
        // Keep a selected version visible even after its last local record is deleted.
        modelVersions = (records.map { it.modelVersion } + listOfNotNull(modelVersion)).distinct().sorted(),
        modelVersion = modelVersion,
        allCount = records.size,
        allPendingCount = records.count { it.pendingSync },
    )
