package com.mobilecloud.recognition.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 类别清单：与仓库 shared/categories.json（冻结后）或 categories.example.json（草案）对应。
 * 类别 ID 与模型输出索引一致（docs/model-contract.md）；界面中文名称由此提供。
 */
@Serializable
data class CategoryDefinition(
    val id: Int,
    @SerialName("label_key") val labelKey: String,
    @SerialName("display_name") val displayName: String,
)

@Serializable
data class CategoryFile(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    val status: String = "draft",
    val categories: List<CategoryDefinition> = emptyList(),
) {
    companion object {
        fun parse(text: String): CategoryFile = CategoryJson.decodeFromString(serializer(), text)

        private val CategoryJson = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
    }
}

/** 类别清单加载失败时的兜底：展示原始标签，纠错面板用空清单提示 */
class CategoryCatalog(val file: CategoryFile) {

    val categories: List<CategoryDefinition> = file.categories.sortedBy { it.id }

    private val byLabelKey: Map<String, CategoryDefinition> =
        categories.associateBy { it.labelKey }

    fun displayNameForLabel(label: String): String =
        byLabelKey[label]?.displayName ?: label

    companion object {
        const val DRAFT_JSON = """{
  "schema_version": 1,
  "status": "draft",
  "categories": [
    {"id": 0, "label_key": "cup", "display_name": "水杯"},
    {"id": 1, "label_key": "umbrella", "display_name": "雨伞"},
    {"id": 2, "label_key": "book", "display_name": "书本"},
    {"id": 3, "label_key": "pencil_case", "display_name": "笔袋"},
    {"id": 4, "label_key": "mouse", "display_name": "鼠标"},
    {"id": 5, "label_key": "keyboard", "display_name": "键盘"},
    {"id": 6, "label_key": "earphones", "display_name": "耳机"},
    {"id": 7, "label_key": "charger", "display_name": "充电器"},
    {"id": 8, "label_key": "key", "display_name": "钥匙"},
    {"id": 9, "label_key": "backpack", "display_name": "背包"}
  ]
}"""

        fun fromText(text: String?): CategoryCatalog =
            CategoryCatalog(
                runCatching { CategoryFile.parse(text ?: DRAFT_JSON) }
                    .getOrElse { CategoryFile.parse(DRAFT_JSON) }
            )
    }
}
