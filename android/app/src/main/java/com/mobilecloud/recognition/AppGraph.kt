package com.mobilecloud.recognition

import android.content.Context
import com.mobilecloud.recognition.camera.PhotoStore
import com.mobilecloud.recognition.data.CategoryCatalog
import com.mobilecloud.recognition.data.local.AppDatabase
import com.mobilecloud.recognition.data.local.RecordDao
import com.mobilecloud.recognition.data.remote.ApiClient
import com.mobilecloud.recognition.data.settings.SettingsStore
import com.mobilecloud.recognition.inference.ModelRepository
import com.mobilecloud.recognition.sync.RecordUploader
import com.mobilecloud.recognition.sync.SyncScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * 轻量服务定位器：课程项目规模下以手动装配替代 DI 框架，降低构建复杂度。
 * init 幂等，App 与 WorkManager Worker 都可能率先调用。
 */
object AppGraph {

    lateinit var appContext: Context
        private set

    lateinit var settings: SettingsStore
        private set
    lateinit var database: AppDatabase
        private set
    lateinit var apiClient: ApiClient
        private set
    lateinit var modelRepository: ModelRepository
        private set
    lateinit var photoStore: PhotoStore
        private set
    lateinit var categoryCatalog: CategoryCatalog
        private set
    lateinit var uploader: RecordUploader
        private set
    lateinit var syncScheduler: SyncScheduler
        private set

    val recordDao: RecordDao get() = database.recordDao()

    @Volatile
    private var initialized = false

    fun init(context: Context) {
        if (initialized) return
        synchronized(this) {
            if (initialized) return
            appContext = context.applicationContext
            settings = SettingsStore(appContext)
            database = AppDatabase.build(appContext)
            apiClient = ApiClient(settings)
            modelRepository = ModelRepository(appContext)
            photoStore = PhotoStore(appContext)
            categoryCatalog = CategoryCatalog.fromText(loadCategoryAsset())
            uploader = RecordUploader(recordDao, apiClient.api)
            syncScheduler = SyncScheduler(appContext)

            syncScheduler.registerNetworkCallback()

            val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
            scope.launch {
                settings.ensureClientId()
                syncSettingsConfig()
            }
            initialized = true
        }
    }

    /** 把持久化设置同步进网络层；设置页保存后也调用 */
    fun syncSettingsConfig() {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        scope.launch {
            val baseUrl = settings.currentBaseUrl()
            val token = settings.currentToken()
            apiClient.updateConfig(baseUrl, token)
        }
    }

    private fun loadCategoryAsset(): String? = try {
        appContext.assets.open("categories.json").use { String(it.readBytes(), Charsets.UTF_8) }
    } catch (_: Exception) {
        null
    }
}
