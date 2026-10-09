package com.mobilecloud.recognition.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.mobilecloud.recognition.AppGraph

/**
 * 后台补传 Worker：网络可用时由 SyncScheduler 触发，也可在记录页手动触发。
 */
class SyncWorker(appContext: Context, params: WorkerParameters) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        AppGraph.init(applicationContext)
        val summary = AppGraph.uploader.syncAll()
        return when {
            summary.success -> Result.success()
            // 有失败记录时用退避重试；超过次数后返回成功结束本次任务，记录保持待传，下次触发继续
            runAttemptCount < MAX_RETRIES -> Result.retry()
            else -> Result.success()
        }
    }

    companion object {
        const val WORK_NAME = "record-sync"
        const val MAX_RETRIES = 3
    }
}
