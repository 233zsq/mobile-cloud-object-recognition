package com.mobilecloud.recognition.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// Shared with the Web dashboard; see docs/ui-style.md.
private val CampusColors = lightColorScheme(
    primary = Color(0xFF183F32),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD7EF78),
    onPrimaryContainer = Color(0xFF17302E),
    secondary = Color(0xFF526B62),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFEDF3EE),
    onSecondaryContainer = Color(0xFF17302E),
    tertiary = Color(0xFF85621D),
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFFFF0CC),
    onTertiaryContainer = Color(0xFF59420F),
    background = Color(0xFFF6F3E8),
    onBackground = Color(0xFF17302E),
    surface = Color(0xFFFFFDF5),
    onSurface = Color(0xFF17302E),
    surfaceVariant = Color(0xFFEDF3EE),
    onSurfaceVariant = Color(0xFF58695D),
    surfaceTint = Color(0xFF16705C),
    outline = Color(0xFF7B9189),
    outlineVariant = Color(0xFFDFE8E4),
    error = Color(0xFFB03A2E),
    onError = Color.White,
    errorContainer = Color(0xFFFCE5E0),
    onErrorContainer = Color(0xFF6B2018),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFF6F3E8),
    surfaceContainer = Color(0xFFE9EDDF),
    surfaceContainerHigh = Color(0xFFE7EFE9),
    surfaceContainerHighest = Color(0xFFDFE8E4),
)

/** Fixed light theme, independent of wallpaper and system night mode. */
@Composable
fun CampusRecognitionTheme(
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = CampusColors,
        typography = Typography(
            headlineLarge = TextStyle(fontFamily = FontFamily.Serif, fontSize = 34.sp, fontWeight = FontWeight.Medium, lineHeight = 40.sp),
            headlineMedium = TextStyle(fontFamily = FontFamily.Serif, fontSize = 29.sp, lineHeight = 36.sp),
            headlineSmall = TextStyle(fontFamily = FontFamily.Serif, fontSize = 25.sp, lineHeight = 32.sp),
            labelSmall = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 16.sp),
        ),
        shapes = Shapes(
            extraSmall = RoundedCornerShape(4.dp),
            small = RoundedCornerShape(8.dp),
            medium = RoundedCornerShape(12.dp),
            large = RoundedCornerShape(16.dp),
            extraLarge = RoundedCornerShape(20.dp),
        ),
        content = content,
    )
}
