package com.mobilecloud.recognition

import android.graphics.Bitmap
import android.os.ParcelFileDescriptor
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.rules.ExternalResource

/** Verifies navigation and SavedStateHandle ViewModel creation without changing records. */
@RunWith(AndroidJUnit4::class)
class RecordsScreenSmokeTest {
    @get:Rule(order = 0) val cameraPermission = object : ExternalResource() {
        override fun before() {
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            val output = instrumentation.uiAutomation.executeShellCommand(
                "pm grant ${instrumentation.targetContext.packageName} android.permission.CAMERA",
            )
            ParcelFileDescriptor.AutoCloseInputStream(output).use { it.readBytes() }
        }
    }
    @get:Rule(order = 1) val compose = createAndroidComposeRule<MainActivity>()

    @Test fun historyOpensWithTheModelFilterAndCapturesTheCurrentLayout() {
        compose.onNodeWithText("记录").performClick()
        compose.onNodeWithText("识别记录").assertIsDisplayed()
        compose.onNodeWithTag("model-version-filter").assertTextContains("全部模型")
        val screenshot = compose.onRoot().captureToImage().asAndroidBitmap()
        val folder = requireNotNull(compose.activity.getExternalFilesDir("ui-checks")).apply { mkdirs() }
        File(folder, "records-model-filter.png").outputStream().use {
            check(screenshot.compress(Bitmap.CompressFormat.PNG, 100, it))
        }
    }
}
