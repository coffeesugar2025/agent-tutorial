package com.example.adminscaffold.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Primary = Color(0xFF2B5B8C)
private val PrimaryDark = Color(0xFF1F2D3D)

private val LightColors = lightColorScheme(
    primary = Primary,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDCE9F7),
    secondary = Color(0xFF409EFF),
    background = Color(0xFFF5F7FA),
    surface = Color.White,
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF7DB3F0),
    secondary = Color(0xFF409EFF),
    primaryContainer = PrimaryDark,
)

@Composable
fun AdminTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content
    )
}
