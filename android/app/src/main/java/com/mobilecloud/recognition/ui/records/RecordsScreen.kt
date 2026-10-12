package com.mobilecloud.recognition.ui.records

import androidx.compose.foundation.Image
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.ui.theme.FieldNotesHeader
import java.io.File
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * 记录页：本地识别记录列表、同步状态展示与手动补传（F03/F04，T07）。
 */
@Composable
fun RecordsScreen(viewModel: RecordsViewModel = viewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(state.message) {
        state.message?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.consumeMessage()
        }
    }

    // 待删除记录：非空时显示确认框（删除为破坏性操作，需二次确认）
    var pendingDelete by remember { mutableStateOf<RecordEntity?>(null) }
    // 清空全部：批量破坏性操作，单独确认
    var showClearAll by remember { mutableStateOf(false) }
    var showActions by remember { mutableStateOf(false) }
    val selection = state.selection

    Scaffold(containerColor = MaterialTheme.colorScheme.background, snackbarHost = { SnackbarHost(snackbarHostState) }) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            FieldNotesHeader("观察记录")
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "按模型查看本机记录与同步状态",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (state.syncing) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                } else {
                    TextButton(onClick = viewModel::syncNow) { Text("同步全部") }
                }
                Box {
                    IconButton(onClick = { showActions = true }) {
                        Icon(Icons.Filled.MoreVert, contentDescription = "记录操作")
                    }
                    DropdownMenu(expanded = showActions, onDismissRequest = { showActions = false }) {
                        DropdownMenuItem(
                            text = { Text("清空全部本地记录", color = MaterialTheme.colorScheme.error) },
                            enabled = selection.allCount > 0,
                            onClick = { showActions = false; showClearAll = true },
                        )
                    }
                }
            }

            Surface(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                shape = MaterialTheme.shapes.medium,
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
            ) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    ModelVersionFilter(selection.modelVersions, selection.modelVersion, viewModel::selectModel)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        RecordMetric("记录", selection.count)
                        RecordMetric("待同步", selection.pendingCount)
                        RecordMetric("已修正", selection.correctedCount)
                    }
                }
            }
            if (selection.modelVersion != null) {
                Text(
                    "当前筛选 ${selection.count} 条 · 本机共 ${selection.allCount} 条",
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Spacer(Modifier.height(10.dp))
            }

            if (selection.records.isEmpty()) {
                Box(modifier = Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            if (selection.modelVersion == null) "暂无观察记录，请到识别页拍照" else "此模型暂无本地记录",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (selection.modelVersion != null) {
                            TextButton(onClick = { viewModel.selectModel(null) }) { Text("查看全部模型") }
                        }
                    }
                }
            } else {
                LazyColumn(modifier = Modifier.weight(1f)) {
                    items(selection.records, key = { it.recordId }) { record ->
                        RecordCard(record, onDelete = { pendingDelete = record })
                    }
                }
            }
        }
    }

    pendingDelete?.let { record ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("删除这条记录？") },
            text = {
                Text(
                    RecordDeletionText.confirm(
                        pendingSync = record.pendingSync,
                        corrected = record.correctedLabel != null,
                    ),
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.deleteRecord(record)
                        pendingDelete = null
                    },
                ) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }) { Text("取消") }
            },
        )
    }

    if (showClearAll) {
        AlertDialog(
            onDismissRequest = { showClearAll = false },
            title = { Text("清空全部本地记录？") },
            text = {
                Text(
                    RecordDeletionText.clearConfirm(
                        total = selection.allCount,
                        pending = selection.allPendingCount,
                    ),
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.clearAllRecords()
                        showClearAll = false
                    },
                ) { Text("清空") }
            },
            dismissButton = {
                TextButton(onClick = { showClearAll = false }) { Text("取消") }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ModelVersionFilter(versions: List<String>, selected: String?, onSelect: (String?) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
        OutlinedTextField(
            value = selected ?: "全部模型",
            onValueChange = {},
            readOnly = true,
            singleLine = true,
            label = { Text("模型版本") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier = Modifier.fillMaxWidth()
                .menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable)
                .testTag("model-version-filter"),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(text = { Text("全部模型") }, onClick = { onSelect(null); expanded = false })
            versions.forEach { version ->
                DropdownMenuItem(
                    text = { Text(version, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    onClick = { onSelect(version); expanded = false },
                )
            }
        }
    }
}

@Composable
private fun RecordMetric(label: String, count: Int) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(count.toString(), style = MaterialTheme.typography.headlineSmall)
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun RecordCard(record: RecordEntity, onDelete: () -> Unit) {
    val catalog = AppGraph.categoryCatalog
    val currentName = catalog.displayNameForLabel(record.displayLabel)
    val originalName = catalog.displayNameForLabel(record.predictedLabel)

    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 5.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Row(modifier = Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            RecordThumbnail(record.photoPath)
            Spacer(Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f)) {
                if (record.correctedLabel != null) {
                    Text("已修正：$currentName", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "原预测：$originalName（保留）",
                        style = MaterialTheme.typography.bodySmall,
                    )
                } else {
                    Text(currentName, style = MaterialTheme.typography.titleMedium)
                }
                Text(
                    "置信度 ${"%.1f".format(record.confidence * 100)}% · 耗时 ${record.latencyMs} ms",
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    formatTime(record.capturedAt),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "${if (record.inferenceSource == "cloud") "云端" else "本地"} · ${record.modelVersion}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                record.lastError?.let {
                    Text(
                        it,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            Spacer(Modifier.width(6.dp))
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Surface(
                    shape = MaterialTheme.shapes.small,
                    color = if (record.pendingSync) MaterialTheme.colorScheme.secondaryContainer
                        else MaterialTheme.colorScheme.primaryContainer,
                ) {
                    Text(
                        if (record.pendingSync) "待同步" else "已同步",
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
                IconButton(onClick = onDelete) {
                    Icon(
                        Icons.Filled.Delete,
                        contentDescription = "删除记录",
                        tint = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

@Composable
private fun RecordThumbnail(photoPath: String?) {
    val bitmap by produceState<ImageBitmap?>(initialValue = null, photoPath) {
        value = photoPath?.let { path ->
            withContext(Dispatchers.IO) {
                runCatching {
                    // 原始照片可达 4000+ 像素，必须按缩略图尺寸采样解码，避免多条记录同时占用数百 MiB
                    AppGraph.photoStore.decodeUpright(File(path), maxDimension = 168)?.asImageBitmap()
                }.getOrNull()
            }
        }
    }
    Box(
        modifier = Modifier.size(56.dp).clip(MaterialTheme.shapes.small),
        contentAlignment = Alignment.Center,
    ) {
        val current = bitmap
        if (current != null) {
            Image(
                bitmap = current,
                contentDescription = "记录照片",
                contentScale = ContentScale.Crop,
                modifier = Modifier.size(56.dp),
            )
        } else {
            Text("无图", style = MaterialTheme.typography.bodySmall)
        }
    }
}

private fun formatTime(epochMillis: Long): String =
    DateTimeFormatter.ofPattern("MM-dd HH:mm:ss")
        .withZone(ZoneId.systemDefault())
        .format(Instant.ofEpochMilli(epochMillis))
