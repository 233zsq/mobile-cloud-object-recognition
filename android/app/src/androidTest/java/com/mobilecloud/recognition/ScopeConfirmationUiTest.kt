package com.mobilecloud.recognition

import android.graphics.Bitmap
import android.graphics.Color
import android.os.ParcelFileDescriptor
import androidx.activity.compose.setContent
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.lifecycle.ViewModelStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.ui.capture.CaptureScreen
import com.mobilecloud.recognition.ui.capture.CaptureViewModel
import com.mobilecloud.recognition.ui.capture.ModelState
import com.mobilecloud.recognition.ui.theme.CampusRecognitionTheme
import java.io.File
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Rule
import org.junit.rules.ExternalResource
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ScopeConfirmationUiTest {
    @get:Rule(order = 0) val cameraPermission = object : ExternalResource() {
        override fun before() {
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                "pm grant ${instrumentation.targetContext.packageName} android.permission.CAMERA",
            )).use { it.readBytes() }
        }
    }
    @get:Rule(order = 1) val compose = createAndroidComposeRule<MainActivity>()

    @Test fun uncertainPhotoOffersExplicitChoiceAndSavesOnlyAfterUserAction(): Unit = runBlocking {
        val records = mutableListOf<RecordEntity>()
        val vm = withContext(Dispatchers.Main) { CaptureViewModel({ records += it }, {}) }
        val store = ViewModelStore().apply { put("scope-ui",vm) }
        withTimeout(20_000) { vm.state.first { it.modelState is ModelState.Ready } }
        var file: File? = null
        try {
            withContext(Dispatchers.Main) {
                compose.activity.setContent { CampusRecognitionTheme { CaptureScreen(AppGraph.categoryCatalog,vm) } }
            }
            for (gray in listOf(80,128,32,192,0,255)) {
                val bitmap = Bitmap.createBitmap(64,64,Bitmap.Config.ARGB_8888).apply { eraseColor(Color.rgb(gray,gray,gray)) }
                try {
                    if (AppGraph.modelRepository.classify(bitmap).scopeDecision?.needsConfirmation == true) {
                        file = AppGraph.photoStore.newPhotoFile().also { image -> image.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) } }
                        break
                    }
                } finally { bitmap.recycle() }
            }
            withContext(Dispatchers.Main) { vm.onPhotoSaved(requireNotNull(file)) }
            val candidate = withTimeout(20_000) { vm.state.first { it.confirmation != null }.confirmation!! }
            compose.onNodeWithTag("photo-confirmation").performScrollTo().assertIsDisplayed()
            compose.waitUntil(5_000) { compose.onAllNodesWithContentDescription("待确认的照片").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithTag("confirm-photo").assertIsEnabled()
            assertEquals(0,records.size)
            saveScreen("scope-confirmation.png")
            compose.onNodeWithText("选择其他类别并保存").performScrollTo().performClick()
            val selected = AppGraph.categoryCatalog.categories.first { it.id != candidate.prediction.index }
            compose.onNodeWithText("保存为${selected.displayName}").performClick()
            withTimeout(20_000) { vm.state.first { it.lastResult != null } }
            compose.onNodeWithTag("photo-confirmation").assertDoesNotExist()
            assertEquals(selected.id,records.single().correctedIndex)
            compose.onNodeWithText("已由你确认并保存").performScrollTo().assertIsDisplayed()
        } finally { withContext(Dispatchers.Main) { store.clear() }; file?.delete() }
    }

    private fun saveScreen(name: String) {
        val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
        val folder = requireNotNull(compose.activity.getExternalFilesDir("ui-checks")).apply { mkdirs() }
        File(folder,name).outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG,100,it)) }
    }
}
