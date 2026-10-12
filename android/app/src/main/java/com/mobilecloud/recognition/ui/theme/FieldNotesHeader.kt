package com.mobilecloud.recognition.ui.theme

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.font.FontFamily
import com.mobilecloud.recognition.R

@Composable
fun BrandMark(modifier: Modifier = Modifier.size(54.dp)) {
    Image(
        painter = painterResource(R.drawable.brand_mark),
        contentDescription = null,
        modifier = modifier.clip(RoundedCornerShape(14.dp)),
    )
}

@Composable
fun FieldNotesHeader(title: String, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth().padding(horizontal = 22.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        BrandMark(Modifier.size(38.dp))
        Spacer(Modifier.width(10.dp))
        Text(title, modifier = Modifier.weight(1f), fontSize = 22.sp, fontFamily = FontFamily.Serif)
        Text("CAMPUS", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
