package com.mobilecloud.recognition.ui.capture

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.UseCaseGroup
import androidx.camera.core.ViewPort
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.mobilecloud.recognition.AppGraph
import java.io.File
import java.util.concurrent.Executors
import android.util.Size
import android.util.Rational
import android.view.Surface

/**
 * 相机预览 + 拍照按钮。ImageCapture 按 display 旋转写入 EXIF，方向在解码时统一应用（T02）。
 * 权限拒绝流程由 [CaptureScreen] 处理（T01）。
 */
@Composable
fun CameraCaptureView(
    captureEnabled: Boolean,
    onPhotoSaved: (File) -> Unit,
    onCaptureError: (String) -> Unit,
    onImportClick: () -> Unit,
    modifier: Modifier = Modifier,
    onCaptureStarted: () -> Unit = {},
    liveActive: Boolean = false,
    onAnalyzeFrame: (ImageProxy) -> Unit = { it.close() },
    onLiveCameraReady: (Boolean) -> Unit = {},
    onLiveCameraUnavailable: () -> Unit = {},
    liveOverlay: (@Composable () -> Unit)? = null,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember { PreviewView(context) }
    val imageCapture = remember {
        ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
            .build()
    }
    var capturing by remember { mutableStateOf(false) }
    var previewSize by remember { mutableStateOf(IntSize.Zero) }
    val analysis = remember {
        @Suppress("DEPRECATION")
        ImageAnalysis.Builder().setTargetResolution(Size(640, 480))
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
    }
    val analyzerExecutor = remember { Executors.newSingleThreadExecutor() }
    val analyzeFrame by rememberUpdatedState(onAnalyzeFrame)
    val cameraReady by rememberUpdatedState(onLiveCameraReady)
    val cameraUnavailable by rememberUpdatedState(onLiveCameraUnavailable)
    val captureError by rememberUpdatedState(onCaptureError)

    DisposableEffect(analyzerExecutor) {
        onDispose {
            analysis.clearAnalyzer()
            // Let the current frame finish and release its bitmap/proxy; never interrupt native inference.
            analyzerExecutor.shutdown()
        }
    }
    DisposableEffect(liveActive, analysis, analyzerExecutor) {
        if (liveActive) analysis.setAnalyzer(analyzerExecutor) { image -> analyzeFrame(image) }
        else analysis.clearAnalyzer()
        onDispose { analysis.clearAnalyzer() }
    }

    DisposableEffect(lifecycleOwner, previewSize) {
        var disposed = false
        var boundProvider: ProcessCameraProvider? = null
        val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
        cameraReady(false)
        if (previewSize.width > 0 && previewSize.height > 0) {
            val future = ProcessCameraProvider.getInstance(context)
            future.addListener({
                if (!disposed) try {
                    val provider = future.get()
                    boundProvider = provider
                    val selector = when {
                        provider.hasCamera(CameraSelector.DEFAULT_BACK_CAMERA) -> CameraSelector.DEFAULT_BACK_CAMERA
                        provider.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA) -> CameraSelector.DEFAULT_FRONT_CAMERA
                        else -> error("设备没有可用相机")
                    }
                    val rotation = previewView.display?.rotation ?: Surface.ROTATION_0
                    imageCapture.targetRotation = rotation
                    analysis.targetRotation = rotation
                    // Shared viewport prevents analysis of regions hidden by the visible preview crop.
                    val viewport = ViewPort.Builder(Rational(previewSize.width, previewSize.height), rotation)
                        .setScaleType(ViewPort.FILL_CENTER).build()
                    val group = UseCaseGroup.Builder().setViewPort(viewport)
                        .addUseCase(preview).addUseCase(imageCapture).addUseCase(analysis).build()
                    try {
                        provider.bindToLifecycle(lifecycleOwner, selector, group)
                        cameraReady(true)
                    } catch (_: Exception) {
                        provider.unbind(preview, imageCapture, analysis)
                        provider.bindToLifecycle(lifecycleOwner, selector, preview, imageCapture)
                        cameraUnavailable()
                    }
                } catch (error: Exception) {
                    captureError("相机绑定失败：${error.message ?: error.javaClass.simpleName}")
                }
            }, ContextCompat.getMainExecutor(context))
        }
        onDispose {
            disposed = true
            cameraReady(false)
            boundProvider?.unbind(preview, imageCapture, analysis)
        }
    }

    Column(modifier = modifier.fillMaxSize()) {
      Box(Modifier.weight(1f).fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(Color(0xFF5D725F))) {
        AndroidView(
            factory = { previewView },
            update = { view ->
                view.display?.let { display ->
                    imageCapture.targetRotation = display.rotation
                    analysis.targetRotation = display.rotation
                }
            },
            modifier = Modifier.fillMaxSize().onSizeChanged { previewSize = it },
        )
        Canvas(Modifier.fillMaxSize().padding(20.dp)) {
            val length = 24.dp.toPx()
            val stroke = 2.dp.toPx()
            val ink = Color(0xFFD7EF78)
            listOf(androidx.compose.ui.geometry.Offset.Zero, androidx.compose.ui.geometry.Offset(size.width, 0f),
                androidx.compose.ui.geometry.Offset(0f, size.height), androidx.compose.ui.geometry.Offset(size.width, size.height)).forEach { point ->
                drawLine(ink, point, point + androidx.compose.ui.geometry.Offset(if (point.x == 0f) length else -length, 0f), stroke)
                drawLine(ink, point, point + androidx.compose.ui.geometry.Offset(0f, if (point.y == 0f) length else -length), stroke)
            }
        }
        if (liveOverlay != null) Box(Modifier.align(Alignment.BottomCenter).padding(12.dp)) { liveOverlay() }
        else Text("把一个主要物品放入画面", Modifier.align(Alignment.BottomCenter).padding(14.dp).background(Color.Black.copy(alpha = .35f), RoundedCornerShape(14.dp)).padding(horizontal = 12.dp, vertical = 5.dp), color = Color.White, style = MaterialTheme.typography.bodySmall)
      }
        Row(
            modifier = Modifier
                .fillMaxWidth().padding(vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedButton(onClick = onImportClick, enabled = captureEnabled,
                modifier = Modifier.weight(.85f).height(56.dp), shape = RoundedCornerShape(18.dp)) {
                Text("选择图片", style = MaterialTheme.typography.labelLarge)
            }
            Box(
                modifier = Modifier.weight(1.3f).height(56.dp).clip(RoundedCornerShape(18.dp))
                .background(if (captureEnabled) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline)
                .semantics { contentDescription = "拍照识别" }
                .clickable(enabled = captureEnabled && !capturing, role = Role.Button) {
                    if (capturing || !captureEnabled) return@clickable
                    capturing = true
                    onCaptureStarted()
                    val file = AppGraph.photoStore.newPhotoFile()
                    val options = ImageCapture.OutputFileOptions.Builder(file).build()
                    imageCapture.takePicture(
                        options,
                        ContextCompat.getMainExecutor(context),
                        object : ImageCapture.OnImageSavedCallback {
                            override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                                capturing = false
                                onPhotoSaved(file)
                            }

                            override fun onError(exception: ImageCaptureException) {
                                capturing = false
                                file.delete()
                                onCaptureError(exception.message ?: "未知相机错误")
                            }
                        },
                    )
                }, contentAlignment = Alignment.Center,
            ) {
                if (capturing) {
                    CircularProgressIndicator(
                        modifier = Modifier.height(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                } else Text("拍照识别", color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.titleMedium)
            }
        }
    }
}

/** 权限被拒时的说明界面（T01）：明确提示、可重新申请、可跳系统设置；申请结果由父页统一处理 */
@Composable
fun CameraPermissionRationale(onRequest: () -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current

    Column(
        modifier = modifier.padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("需要相机权限", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(8.dp))
        Text(
            "识别功能使用相机拍摄校园物品照片。照片保存在应用私有目录，" +
                "本地模式仅上传识别结果；选择云端模式时会上传去除元数据的压缩图片供识别。",
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(16.dp))
        Button(onClick = onRequest) { Text("重新申请权限") }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = { openAppSettings(context) }) { Text("去系统设置开启") }
    }
}

private fun openAppSettings(context: Context) {
    val intent = Intent(
        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
        Uri.fromParts("package", context.packageName, null),
    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { context.startActivity(intent) }
}

/** 简单包装便于调用方检查权限 */
fun hasCameraPermission(context: Context): Boolean =
    ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
        PackageManager.PERMISSION_GRANTED
