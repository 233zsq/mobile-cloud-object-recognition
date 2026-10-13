package com.mobilecloud.recognition

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Rect
import android.os.SystemClock
import androidx.camera.core.ImageInfo
import androidx.camera.core.ImageProxy
import androidx.lifecycle.ViewModelStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.camera.PreviewFrameBitmap
import com.mobilecloud.recognition.camera.decodeAssetUpright
import com.mobilecloud.recognition.ui.capture.CaptureViewModel
import com.mobilecloud.recognition.ui.capture.InferenceMode
import com.mobilecloud.recognition.ui.capture.ModelState
import java.lang.reflect.Proxy
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LivePreviewIntegrationTest {
    /** A decoded frame fixture isolates rotation/crop/lifetime from hardware-specific YUV layouts. */
    private fun frame(bitmap: Bitmap, rotation: Int = 0, crop: Rect = Rect(0, 0, bitmap.width, bitmap.height),
        closed: () -> Unit = {}): ImageProxy {
        val info = Proxy.newProxyInstance(ImageInfo::class.java.classLoader, arrayOf(ImageInfo::class.java)) { _, method, _ ->
            when (method.name) { "getRotationDegrees" -> rotation; "getTimestamp" -> SystemClock.elapsedRealtimeNanos(); else -> null }
        } as ImageInfo
        return Proxy.newProxyInstance(ImageProxy::class.java.classLoader, arrayOf(ImageProxy::class.java)) { _, method, _ ->
            when (method.name) {
                "toBitmap" -> bitmap.copy(Bitmap.Config.ARGB_8888, false)
                "getCropRect" -> crop
                "getImageInfo" -> info
                "getWidth" -> bitmap.width
                "getHeight" -> bitmap.height
                "close" -> { closed(); null }
                else -> null
            }
        } as ImageProxy
    }

    @Test fun cropAndRotationPreserveRgbAndProduceAnOwnedBitmap() {
        val source = Bitmap.createBitmap(4, 3, Bitmap.Config.ARGB_8888)
        source.setPixel(1, 0, Color.RED); source.setPixel(2, 0, Color.GREEN)
        source.setPixel(1, 1, Color.BLUE); source.setPixel(2, 1, Color.YELLOW)
        val result = PreviewFrameBitmap.upright(frame(source, 90, Rect(1, 0, 3, 2)))
        try {
            assertEquals(2, result.width); assertEquals(2, result.height)
            assertEquals(Color.BLUE, result.getPixel(0, 0)); assertEquals(Color.RED, result.getPixel(1, 0))
            assertEquals(Color.YELLOW, result.getPixel(0, 1)); assertEquals(Color.GREEN, result.getPixel(1, 1))
            assertFalse(source.isRecycled)
        } finally { source.recycle(); result.recycle() }
    }

    @Test fun realModelPreviewDoesNotSavePhotosOrRecordsAndPausesForCloudAndCapture() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        AppGraph.init(context)
        val viewModel = withContext(Dispatchers.Main) { CaptureViewModel() }
        val store = ViewModelStore().apply { put("live-preview-test", viewModel) }
        withTimeout(20_000) { viewModel.state.first { it.modelState !is ModelState.Loading } }
        assertTrue(viewModel.state.value.modelState is ModelState.Ready)
        val records = AppGraph.recordDao.count()
        val photoFiles = context.filesDir.walkTopDown().filter { it.isFile && it.extension == "jpg" }.map { it.path }.toSet()
        val bitmap = requireNotNull(decodeAssetUpright(context, "models/examples/oi-30d38acdacfe06d0.jpg"))
        var closes = 0
        try {
            viewModel.analyzePreviewFrame(frame(bitmap) { closes++ })
            assertNull(viewModel.state.value.liveObservation)
            withContext(Dispatchers.Main) {
                viewModel.setLiveEnabled(true); viewModel.setLiveCameraReady(true); viewModel.setLivePreviewActive(true)
            }
            repeat(3) {
                viewModel.analyzePreviewFrame(frame(bitmap) { closes++ })
                delay(550)
            }
            assertTrue(requireNotNull(viewModel.state.value.liveObservation).stable)
            assertEquals("cup", viewModel.state.value.liveObservation?.prediction?.label)
            assertEquals(records, AppGraph.recordDao.count())
            assertEquals(photoFiles, context.filesDir.walkTopDown().filter { it.isFile && it.extension == "jpg" }.map { it.path }.toSet())
            withContext(Dispatchers.Main) { viewModel.selectMode(InferenceMode.CLOUD) }
            assertFalse(viewModel.state.value.liveActive)
            assertNull(viewModel.state.value.liveObservation)
            viewModel.analyzePreviewFrame(frame(bitmap) { closes++ })
            withContext(Dispatchers.Main) {
                viewModel.selectMode(InferenceMode.DEVICE); viewModel.setLivePreviewActive(true); viewModel.onCaptureStarted()
            }
            assertFalse(viewModel.state.value.liveActive)
            viewModel.analyzePreviewFrame(frame(bitmap) { closes++ })
            assertEquals(6, closes)
            assertEquals(records, AppGraph.recordDao.count())
        } finally { withContext(Dispatchers.Main) { viewModel.setLivePreviewActive(false); store.clear() }; bitmap.recycle() }
    }

    @Test fun previewDoesNotQueueBehindModelMaintenance() = runBlocking {
        AppGraph.init(InstrumentationRegistry.getInstrumentation().targetContext)
        AppGraph.modelRepository.info()
        val locked = CountDownLatch(1)
        val release = CompletableDeferred<Unit>()
        val maintenance = launch(Dispatchers.Default) { AppGraph.modelRepository.withBundle { locked.countDown(); release.await() } }
        assertTrue(locked.await(5, TimeUnit.SECONDS))
        val bitmap = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
        try { assertNull(withTimeout(1000) { AppGraph.modelRepository.tryClassifyPreview(bitmap) }) }
        finally { bitmap.recycle(); release.complete(Unit); maintenance.join() }
    }
}
