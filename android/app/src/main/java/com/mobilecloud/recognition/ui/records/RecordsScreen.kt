package com.mobilecloud.recognition.ui.records

import androidx.compose.foundation.Image
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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
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
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.data.local.RecordEntity
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

    Scaffold(snackbarHost = { SnackbarHost(snackbarHostState) }) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("识别记录", style = MaterialTheme.typography.titleLarge)
                    Text(
                        "共 ${state.total} 条 · 待同步 ${state.pendingCount} 条",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                if (state.syncing) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                } else {
                    TextButton(onClick = viewModel::syncNow) { Text("立即同步") }
                }
            }

            if (state.records.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("暂无识别记录，请到采集页拍照", style = MaterialTheme.typography.bodyMedium)
                }
            } else {
                LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(state.records, key = { it.recordId }) { record ->
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
}

@Composable
private fun RecordCard(record: RecordEntity, onDelete: () -> Unit) {
    val catalog = AppGraph.categoryCatalog
    val currentName = catalog.displayNameForLabel(record.displayLabel)
    val originalName = catalog.displayNameForLabel(record.predictedLabel)

    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row(modifier = Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
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
                AssistChip(
                    onClick = {},
                    label = {
                        Text(
                            when {
                                record.pendingSync -> "待同步"
                                else -> "已同步"
                            }
                        )
                    },
                )
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
        modifier = Modifier.size(56.dp),
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
