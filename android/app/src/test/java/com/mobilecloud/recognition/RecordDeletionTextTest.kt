package com.mobilecloud.recognition

import com.mobilecloud.recognition.ui.records.RecordDeletionText
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 删除记录提示文案：删除只作用于本机，已入库记录必须明确告知云端不受影响。
 */
class RecordDeletionTextTest {

    @Test
    fun `pending record warns it will never upload`() {
        val text = RecordDeletionText.confirm(pendingSync = true, corrected = false)
        assertTrue(text, text.contains("无法恢复"))
        assertTrue(text, text.contains("不会再上传"))
        assertTrue(text, !text.contains("云端数据仍然保留"))
    }

    @Test
    fun `uploaded record states cloud copy is kept`() {
        val text = RecordDeletionText.confirm(pendingSync = false, corrected = false)
        assertTrue(text, text.contains("已同步到云端"))
        assertTrue(text, text.contains("云端数据仍然保留"))
    }

    @Test
    fun `corrected record mentions correction is removed too`() {
        val text = RecordDeletionText.confirm(pendingSync = false, corrected = true)
        assertTrue(text, text.contains("人工修正记录会一并删除"))
    }

    @Test
    fun `result message distinguishes uploaded and pending`() {
        assertTrue(RecordDeletionText.result(uploaded = true).contains("云端已入库的数据未受影响"))
        assertTrue(RecordDeletionText.result(uploaded = false).contains("未同步"))
    }
}