plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.oxphone.companion"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.oxphone.companion"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
        // Tokens are never committed; provide via local.properties or env.
        val adminToken = providers.gradleProperty("GATEWAY_ADMIN_TOKEN")
            .orElse(System.getenv("GATEWAY_ADMIN_TOKEN") ?: "")
            .get()
        buildConfigField("String", "GATEWAY_ADMIN_TOKEN", "\"$adminToken\"")
        // Owner pairing token sent as `Authorization: Bearer` on every call.
        val gatewayToken = providers.gradleProperty("GATEWAY_TOKEN")
            .orElse(System.getenv("GATEWAY_TOKEN") ?: "")
            .get()
        buildConfigField("String", "GATEWAY_TOKEN", "\"$gatewayToken\"")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.5")
    implementation("androidx.navigation:navigation-compose:2.8.0")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-kotlinx-serialization:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.2")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
