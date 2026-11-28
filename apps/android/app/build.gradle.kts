plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
    // Crashlytics SDK는 이 플러그인이 넣는 build ID가 없으면 시작할 때 앱을 종료한다. google-services 플러그인은 쓰지 않는다.
    alias(libs.plugins.crashlytics)
}

android {
    namespace = "dev.smallnext.app"
    // Compose BOM 2026.09 libraries require compiling against API 37.
    compileSdk = 37
    buildToolsVersion = "36.0.0"

    defaultConfig {
        applicationId = "dev.smallnext.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // Crashlytics와 서버 AI의 공개 클라이언트 설정. Git 밖(~/.gradle/gradle.properties 또는 -P)에서만 받는다. 없으면 빈 값이다.
        // 서버 AI 값의 검증은 앱의 `ServerAI`가 한다. CAPTCHA 두 값은 하나라도 있으면 서버 AI를 `사용 불가`로 둔다.
        val keys = listOf("FIREBASE_APP_ID", "FIREBASE_SENDER_ID", "FIREBASE_PROJECT_ID", "FIREBASE_API_KEY") +
            listOf("API_BASE_URL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "PRIVACY_POLICY_URL") +
            listOf("AUTH_CAPTCHA_URL", "TURNSTILE_SITE_KEY")
        for (key in keys) {
            val value = providers.gradleProperty("SMALLNEXT_$key").getOrElse("")
            val literal = value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r")
            buildConfigField("String", key, "\"$literal\"")
        }
    }
    buildTypes {
        all {
            // minify OFF라 올릴 매핑이 없다. 업로드에는 google-services 설정도 필요하다.
            configure<com.google.firebase.crashlytics.buildtools.gradle.CrashlyticsExtension> {
                mappingFileUploadEnabled = false
            }
        }
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        buildConfig = true
        compose = true
    }
}

// The app bundles the repository's single flag registry; no copy is committed.
abstract class BundleFeatureFlags : DefaultTask() {
    @get:InputFile
    @get:PathSensitive(PathSensitivity.NONE)
    abstract val registry: RegularFileProperty

    @get:OutputDirectory
    abstract val assets: DirectoryProperty

    @TaskAction
    fun copy() {
        registry.get().asFile.copyTo(assets.file("feature-flags.json").get().asFile, overwrite = true)
    }
}

val bundleFeatureFlags = tasks.register<BundleFeatureFlags>("bundleFeatureFlags") {
    registry.set(rootProject.layout.projectDirectory.file("../../config/feature-flags.json"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(bundleFeatureFlags, BundleFeatureFlags::assets)
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.activity.compose)
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)
    implementation(libs.okhttp)
    // Auth만 쓴다. Postgrest·Realtime·Storage 등 다른 모듈은 넣지 않는다.
    implementation(libs.supabase.auth)
    implementation(libs.ktor.client.okhttp)
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.crashlytics)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.runner)
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test.junit4)
    debugImplementation(libs.compose.ui.test.manifest)
}

// Compiler outputs can be cached; CI tests must execute on each runner/device.
if (System.getenv("CI") == "true") {
    tasks.withType<org.gradle.api.tasks.testing.Test>().configureEach {
        outputs.upToDateWhen { false }
        outputs.cacheIf { false }
    }
    tasks.matching {
        it.name.startsWith("connected") && it.name.endsWith("AndroidTest")
    }.configureEach {
        outputs.upToDateWhen { false }
        outputs.cacheIf { false }
    }
}
