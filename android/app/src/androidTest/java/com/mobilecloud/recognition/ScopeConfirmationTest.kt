package com.mobilecloud.recognition

import android.graphics.Bitmap
import android.graphics.Color
import androidx.lifecycle.ViewModelStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.ui.capture.CaptureViewModel
import com.mobilecloud.recognition.ui.capture.ModelState
import com.mobilecloud.recognition.ui.capture.InferenceMode
import java.io.File
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Synthetic fixtures check the actual model-to-confirmation flow, not unknown detection accuracy. */
@RunWith(AndroidJUnit4::class)
class ScopeConfirmationTest {
    @Test fun clearKnownPhotoStillUsesTheOriginalAutomaticRecordFlow() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        AppGraph.init(context)
        val records = mutableListOf<RecordEntity>()
        val vm = withContext(Dispatchers.Main) { CaptureViewModel({ records += it }, {}) }
        val store = ViewModelStore().apply { put("scope-test",vm) }
        withTimeout(20_000) { vm.state.first { it.modelState is ModelState.Ready } }
        val file = AppGraph.photoStore.newPhotoFile()
        try {
            context.assets.open("models/examples/oi-30d38acdacfe06d0.jpg").use { input -> file.outputStream().use { input.copyTo(it) } }
            withContext(Dispatchers.Main) { vm.onPhotoSaved(file) }
            withTimeout(20_000) { vm.state.first { it.lastResult != null || it.failedPhoto || it.confirmation != null } }
            assertNull(vm.state.value.confirmation)
            assertFalse(vm.state.value.failedPhoto)
            assertEquals("cup",records.single().predictedLabel)
            assertEquals(0,records.single().revision)
            assertFalse(vm.state.value.lastResult!!.manuallyConfirmed)
        } finally { withContext(Dispatchers.Main) { store.clear() }; file.delete() }
    }

    private suspend fun ambiguousPhoto(): File {
        for (gray in listOf(80,128,32,192,0,255)) {
            val bitmap = Bitmap.createBitmap(64,64,Bitmap.Config.ARGB_8888).apply { eraseColor(Color.rgb(gray,gray,gray)) }
            try {
                if (AppGraph.modelRepository.classify(bitmap).scopeDecision?.needsConfirmation == true) {
                    return AppGraph.photoStore.newPhotoFile().also { file ->
                        file.outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG,100,it)) }
                    }
                }
            } finally { bitmap.recycle() }
        }
        error("Synthetic fixture produced no uncertain result")
    }

    @Test fun uncertainPhotoNeedsExplicitConfirmationAndPreservesTheOriginalPrediction() = runBlocking {
        AppGraph.init(InstrumentationRegistry.getInstrumentation().targetContext)
        val records = mutableListOf<RecordEntity>()
        var syncRequests = 0
        val vm = withContext(Dispatchers.Main) { CaptureViewModel({ records += it }, { syncRequests++ }) }
        val store = ViewModelStore().apply { put("scope-test",vm) }
        withTimeout(20_000) { vm.state.first { it.modelState is ModelState.Ready } }
        val file = ambiguousPhoto()
        try {
            withContext(Dispatchers.Main) { vm.onCaptureStarted(); vm.onPhotoSaved(file) }
            val candidate = withTimeout(20_000) { vm.state.first { it.confirmation != null }.confirmation!! }
            assertEquals(0,records.size); assertTrue(file.exists())
            withContext(Dispatchers.Main) { vm.selectMode(InferenceMode.CLOUD); vm.confirmPhoto(-1) }
            assertEquals(InferenceMode.DEVICE,vm.state.value.mode)
            assertEquals(0,records.size)
            val selected = (candidate.prediction.index+1)%10
            withContext(Dispatchers.Main) { vm.confirmPhoto(selected) }
            withTimeout(20_000) { vm.state.first { it.lastResult != null && !it.capturing } }
            val record = records.single()
            assertEquals(candidate.prediction.index,record.predictedIndex)
            assertEquals(candidate.prediction.label,record.predictedLabel)
            assertEquals(selected,record.correctedIndex)
            assertEquals(1,record.revision)
            assertTrue(record.correctionPending)
            assertTrue(vm.state.value.lastResult!!.manuallyConfirmed)
            // Result publication precedes scheduling sync; drain the main-thread save callback first.
            withContext(Dispatchers.Main) { assertEquals(1,syncRequests) }
        } finally { withContext(Dispatchers.Main) { store.clear() }; file.delete() }
    }

    @Test fun discardedUncertainPhotoCreatesNoRecordAndIsRemovedFromPrivateStorage() = runBlocking {
        AppGraph.init(InstrumentationRegistry.getInstrumentation().targetContext)
        var writes = 0
        val vm = withContext(Dispatchers.Main) { CaptureViewModel({ writes++ }, {}) }
        val store = ViewModelStore().apply { put("scope-test",vm) }
        withTimeout(20_000) { vm.state.first { it.modelState is ModelState.Ready } }
        val file = ambiguousPhoto()
        try {
            withContext(Dispatchers.Main) { vm.onPhotoSaved(file) }
            withTimeout(20_000) { vm.state.first { it.confirmation != null } }
            withContext(Dispatchers.Main) { vm.discardConfirmation() }
            assertNull(vm.state.value.confirmation); assertFalse(file.exists()); assertEquals(0,writes)
        } finally { withContext(Dispatchers.Main) { store.clear() }; file.delete() }
    }
}
