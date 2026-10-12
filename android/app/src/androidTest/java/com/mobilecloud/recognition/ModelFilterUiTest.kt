package com.mobilecloud.recognition

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.mobilecloud.recognition.ui.records.ModelVersionFilter
import com.mobilecloud.recognition.ui.theme.CampusRecognitionTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Exercises the actual dropdown without creating/uploading any recognition records. */
@RunWith(AndroidJUnit4::class)
class ModelFilterUiTest {
    @get:Rule val compose = createComposeRule()

    @Test fun selectSpecificModelThenReturnToAllModels() {
        val selected = mutableStateOf<String?>(null)
        compose.setContent {
            CampusRecognitionTheme {
                ModelVersionFilter(listOf("campus-evolve-v2", "campus-gpu-v1"), selected.value) { selected.value = it }
            }
        }
        compose.onNodeWithTag("model-version-filter").performClick()
        compose.onNodeWithText("campus-gpu-v1").performClick()
        compose.runOnIdle { assertEquals("campus-gpu-v1", selected.value) }
        compose.onNodeWithTag("model-version-filter").performClick()
        compose.onNodeWithText("全部模型").performClick()
        compose.runOnIdle { assertEquals(null, selected.value) }
    }
}
