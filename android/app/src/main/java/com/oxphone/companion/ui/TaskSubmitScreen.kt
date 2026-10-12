package com.oxphone.companion.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.oxphone.companion.CompanionViewModel

private val CLASSIFICATIONS = listOf("public", "internal", "confidential", "secret")
private val CAPABILITY_PRESETS = mapOf(
    "On-device (summarize)" to listOf("summarize"),
    "On-device (reminder)" to listOf("reminder"),
    "Code worker" to listOf("code"),
    "Paid translate" to listOf("translate"),
)

/** SPEC B: task text, classification picker, worker picker, submit → gateway. */
@Composable
fun TaskSubmitScreen(vm: CompanionViewModel, onSubmitted: () -> Unit) {
    val state by vm.state.collectAsState()
    var taskText by remember { mutableStateOf("") }
    var classification by remember { mutableStateOf(CLASSIFICATIONS.first()) }
    var preset by remember { mutableStateOf(CAPABILITY_PRESETS.keys.first()) }
    var budgetText by remember { mutableStateOf("0") }

    Column(Modifier.fillMaxSize().padding(16.dp),
           verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Submit task", style = MaterialTheme.typography.headlineSmall)

        OutlinedTextField(
            value = taskText,
            onValueChange = { taskText = it },
            label = { Text("Task") },
            modifier = Modifier.fillMaxWidth(),
        )

        Text("Classification")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CLASSIFICATIONS.forEach { c ->
                FilterChip(
                    selected = classification == c,
                    onClick = { classification = c },
                    label = { Text(c) },
                )
            }
        }

        Text("Worker / capability")
        CAPABILITY_PRESETS.keys.forEach { p ->
            Row {
                RadioButton(selected = preset == p, onClick = { preset = p })
                Text(p, Modifier.padding(start = 4.dp))
            }
        }

        OutlinedTextField(
            value = budgetText,
            onValueChange = { budgetText = it.filter(Char::isDigit) },
            label = { Text("Budget (cents)") },
            modifier = Modifier.fillMaxWidth(),
        )

        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

        Button(
            enabled = taskText.isNotBlank() && !state.submitting,
            onClick = {
                vm.submitTask(
                    taskText = taskText,
                    classification = classification,
                    capabilities = CAPABILITY_PRESETS.getValue(preset),
                    budgetCents = budgetText.toIntOrNull() ?: 0,
                )
                onSubmitted()
            },
        ) {
            Text(if (state.submitting) "Submitting…" else "Submit to gateway")
        }
    }
}
