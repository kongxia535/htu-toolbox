import java.util.Properties

plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val appVersion = Properties().apply {
    rootProject.file("version.properties").inputStream().use { load(it) }
}
android {
    namespace = "io.htu.toolbox"
    compileSdk = 36
    defaultConfig {
        applicationId = "io.htu.toolbox"
        minSdk = 26
        targetSdk = 36
        versionCode = appVersion.getProperty("versionCode").toInt()
        versionName = appVersion.getProperty("versionName")
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildTypes { getByName("release") { isMinifyEnabled = false } }
}
dependencies { testImplementation("junit:junit:4.13.2") }
