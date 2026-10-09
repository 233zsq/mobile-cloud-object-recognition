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

    // ---- 清空全部 ----

    @Test
    fun `clear confirm reports totals, pending and cloud retention`() {
        val text = RecordDeletionText.clearConfirm(total = 22, pending = 18)
        assertTrue(text, text.contains("全部 22 条"))
        assertTrue(text, text.contains("18 条尚未同步"))
        assertTrue(text, text.contains("已同步到云端的 4 条记录在服务端仍然保留"))
        assertTrue(text, text.contains("无法恢复"))
    }

    @Test
    fun `clear confirm without pending omits the pending sentence`() {
        val text = RecordDeletionText.clearConfirm(total = 3, pending = 0)
        assertTrue(text, !text.contains("尚未同步"))
        assertTrue(text, text.contains("3 条记录在服务端仍然保留"))
    }

    @Test
    fun `clear confirm with only pending omits the retention sentence`() {
        val text = RecordDeletionText.clearConfirm(total = 5, pending = 5)
        assertTrue(text, !text.contains("仍然保留"))
        assertTrue(text, text.contains("5 条尚未同步"))
    }

    @Test
    fun `clear result mentions abandoned uploads when pending existed`() {
        assertTrue(RecordDeletionText.clearResult(total = 22, pending = 18).contains("已放弃上传"))
        assertTrue(!RecordDeletionText.clearResult(total = 4, pending = 0).contains("已放弃上传"))
    }
}