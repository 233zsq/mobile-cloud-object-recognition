package com.mobilecloud.recognition.ui.capture

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
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
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mobilecloud.recognition.data.CategoryCatalog
import com.mobilecloud.recognition.inference.ModelBundle

/**
 * 采集页：权限流程 → 相机预览拍照 → 端侧推理 → 结果卡（类别/置信度/耗时/模型版本）→ 纠错面板。
 * 断网时整条链路本地完成，不受服务端影响（F01/F02/F03）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaptureScreen(
    catalog: CategoryCatalog,
    viewModel: CaptureViewModel = viewModel(),
) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    var hasPermission by remember {
        mutableStateOf(hasCameraPermission(context))
    }
    // 首次申请与说明页「重新申请」共用同一个 launcher，结果统一回写 hasPermission
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> hasPermission = granted }

    LaunchedEffect(Unit) {
        if (!hasPermission) permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    // 从系统设置开启权限后返回时刷新状态（T01）
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                hasPermission = hasCameraPermission(context)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    LaunchedEffect(state.message) {
        state.message?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.consumeMessage()
        }
    }

    Scaffold(snackbarHost = { SnackbarHost(snackbarHostState) }) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            ModelStatusBar(state.modelState, onRetry = viewModel::loadModel)

            Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                if (hasPermission) {
                    CameraCaptureView(
                        captureEnabled = state.modelState is ModelState.Ready && !state.capturing,
                        onPhotoSaved = viewModel::onPhotoSaved,
                        onCaptureError = viewModel::onCaptureError,
                    )
                } else {
                    CameraPermissionRationale(
                        onRequest = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            }

            state.lastResult?.let { result ->
                ResultCard(
                    result = result,
                    onCorrect = viewModel::startCorrection,
                )
            }
        }
    }

    if (state.showCorrectionSheet) {
        val result = state.lastResult
        CorrectionSheet(
            catalog = catalog,
            originalDisplayName = result?.displayName ?: "",
            onSelect = viewModel::applyCorrection,
            onDismiss = viewModel::dismissCorrection,
        )
    }
}

@Composable
private fun ModelStatusBar(modelState: ModelState, onRetry: () -> Unit) {
    when (modelState) {
        is ModelState.Loading -> Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(8.dp))
            Text("正在加载模型…", style = MaterialTheme.typography.bodySmall)
        }

        is ModelState.Ready -> Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AssistChip(
                onClick = {},
                label = { Text("模型 ${modelState.info.modelVersion}") },
            )
            Spacer(Modifier.width(8.dp))
            Text(
                "输入 ${modelState.info.inputShape.joinToString("×")} · 阈值 ${modelState.info.lowConfidenceThreshold}",
                style = MaterialTheme.typography.bodySmall,
            )
        }

        is ModelState.Error -> Card(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.errorContainer,
            ),
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text("模型加载失败", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(4.dp))
                Text(modelState.message, style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(8.dp))
                Button(onClick = onRetry) { Text("重新加载") }
            }
        }
    }
}

@Composable
private fun ResultCard(result: CaptureResult, onCorrect: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().padding(12.dp)) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                result.photoPreview?.let { preview ->
                    Image(
                        bitmap = preview,
                        contentDescription = "拍摄照片",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.size(72.dp),
                    )
                    Spacer(Modifier.width(12.dp))
                }
                Column(modifier = Modifier.weight(1f)) {
                    if (result.correctedDisplayName != null) {
                        Text(
                            "已修正：${result.correctedDisplayName}",
                            style = MaterialTheme.typography.titleLarge,
                        )
                        Text(
                            "原预测：${result.displayName}（保留）",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    } else {
                        Text(result.displayName, style = MaterialTheme.typography.titleLarge)
                    }
                    Text(
                        "置信度 ${(result.prediction.confidence * 100).format1()}%",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        "耗时 ${result.prediction.totalMs} ms（预处理 ${result.prediction.preprocessMs} + 推理 ${result.prediction.inferenceMs}）",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            if (result.lowConfidence && result.correctedDisplayName == null) {
                Spacer(Modifier.height(8.dp))
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer)) {
                    Text(
                        "置信度低于阈值，该结果需要确认，建议人工修正类别",
                        modifier = Modifier.padding(8.dp),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            Spacer(Modifier.height(8.dp))
            Row {
                Button(onClick = onCorrect) {
                    Text(if (result.correctedDisplayName == null) "修正类别" else "再次修正")
                }
                Spacer(Modifier.width(8.dp))
                AssistChip(onClick = {}, label = { Text("模型 ${result.prediction.modelVersion}") })
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CorrectionSheet(
    catalog: CategoryCatalog,
    originalDisplayName: String,
    onSelect: (Int, String) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("选择正确类别", style = MaterialTheme.typography.titleMedium)
            Text(
                "原预测「$originalDisplayName」将被保留，仅追加人工修正（修订号自动递增）",
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.height(12.dp))
            if (catalog.categories.isEmpty()) {
                Text("类别清单未加载，请检查 assets/categories.json")
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    catalog.categories.chunked(3).forEach { rowCategories ->
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            rowCategories.forEach { category ->
                                AssistChip(
                                    onClick = { onSelect(category.id, category.displayName) },
                                    label = { Text(category.displayName) },
                                )
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

private fun Float.format1(): String = "%,.1f".format(this)
