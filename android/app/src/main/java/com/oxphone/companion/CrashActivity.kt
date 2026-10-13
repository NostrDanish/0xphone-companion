package com.oxphone.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp

/** Displays the stack trace of an uncaught exception (debug builds). */
class CrashActivity : ComponentActivity() {
    companion object { const val EXTRA_TRACE = "trace" }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val trace = intent.getStringExtra(EXTRA_TRACE) ?: "no trace"
        setContent {
            MaterialTheme {
                val clipboard = LocalClipboardManager.current
                Column(Modifier.fillMaxSize().padding(16.dp)
                       .verticalScroll(rememberScrollState()),
                       verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("0xPhone Companion crashed",
                         style = MaterialTheme.typography.headlineSmall)
                    Text("Copy this trace and report it:",
                         style = MaterialTheme.typography.bodyMedium)
                    Button(onClick = { clipboard.setText(AnnotatedString(trace)) }) {
                        Text("Copy stack trace")
                    }
                    Surface(tonalElevation = 2.dp) {
                        Text(trace, Modifier.padding(12.dp),
                             fontFamily = FontFamily.Monospace,
                             style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
}
