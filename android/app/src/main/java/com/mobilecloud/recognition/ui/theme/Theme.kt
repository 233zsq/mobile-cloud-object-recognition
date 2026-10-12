package com.mobilecloud.recognition.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

// Shared with the Web dashboard; see docs/ui-style.md.
private val CampusColors = lightColorScheme(
    primary = Color(0xFF16705C),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDDEFE7),
    onPrimaryContainer = Color(0xFF17302E),
    secondary = Color(0xFF526B62),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFEDF3EE),
    onSecondaryContainer = Color(0xFF17302E),
    tertiary = Color(0xFF85621D),
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFFFF0CC),
    onTertiaryContainer = Color(0xFF59420F),
    background = Color(0xFFF3F6F2),
    onBackground = Color(0xFF17302E),
    surface = Color.White,
    onSurface = Color(0xFF17302E),
    surfaceVariant = Color(0xFFEDF3EE),
    onSurfaceVariant = Color(0xFF667A77),
    surfaceTint = Color(0xFF16705C),
    outline = Color(0xFF7B9189),
    outlineVariant = Color(0xFFDFE8E4),
    error = Color(0xFFB03A2E),
    onError = Color.White,
    errorContainer = Color(0xFFFCE5E0),
    onErrorContainer = Color(0xFF6B2018),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFF8FAF7),
    surfaceContainer = Color(0xFFEDF3EE),
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
