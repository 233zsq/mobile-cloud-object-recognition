package com.mobilecloud.recognition.sync

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/**
 * 同步触发器：
 * 1. 新记录入库后主动 requestSync；
 * 2. 注册网络回调，恢复联网时自动补传（T07）；
 * 3. 记录页「立即同步」手动触发。
 */
class SyncScheduler(private val context: Context) {

    private var networkCallbackRegistered = false

    fun requestSync() {
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context)
            .enqueueUniqueWork(SyncWorker.WORK_NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    /** 在 App 初始化时调用一次；恢复网络后自动安排一次同步 */
    fun registerNetworkCallback() {
        if (networkCallbackRegistered) return
        val connectivityManager =
            context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                requestSync()
            }
        }
        runCatching { connectivityManager.registerNetworkCallback(request, callback) }
            .onSuccess { networkCallbackRegistered = true }
    }
}
