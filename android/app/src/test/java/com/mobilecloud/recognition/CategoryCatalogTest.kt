package com.mobilecloud.recognition

import com.mobilecloud.recognition.data.CategoryCatalog
import com.mobilecloud.recognition.data.CategoryFile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CategoryCatalogTest {

    @Test
    fun `draft json parses ten categories`() {
        val catalog = CategoryCatalog.fromText(CategoryCatalog.DRAFT_JSON)
        assertEquals(10, catalog.categories.size)
        assertEquals("cup", catalog.categories[0].labelKey)
        assertEquals("水杯", catalog.categories[0].displayName)
        assertEquals("backpack", catalog.categories[9].labelKey)
    }

    @Test
    fun `display name falls back to raw label`() {
        val catalog = CategoryCatalog.fromText(CategoryCatalog.DRAFT_JSON)
        assertEquals("键盘", catalog.displayNameForLabel("keyboard"))
        // 占位模型可能输出非清单标签，此时展示原始标签
        assertEquals("goldfish", catalog.displayNameForLabel("goldfish"))
    }

    @Test
    fun `broken json falls back to draft`() {
        val catalog = CategoryCatalog.fromText("{not json")
        assertEquals(10, catalog.categories.size)
    }

    @Test
    fun `null text falls back to draft`() {
        val catalog = CategoryCatalog.fromText(null)
        assertTrue(catalog.categories.isNotEmpty())
    }

    @Test
    fun `category file parses schema`() {
        val file = CategoryFile.parse(
            """
            {"schema_version":1,"status":"draft","categories":[
              {"id":0,"label_key":"cup","display_name":"水杯"}]}
            """.trimIndent(),
        )
        assertEquals(1, file.categories.size)
        assertEquals("cup", file.categories[0].labelKey)
    }
}
