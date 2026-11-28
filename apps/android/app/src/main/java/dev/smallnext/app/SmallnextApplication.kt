package dev.smallnext.app

import android.app.Application
import dev.smallnext.app.auth.KeystoreSessionStore
import dev.smallnext.app.auth.SupabaseAnonymousIdentity
import dev.smallnext.app.data.AppDatabase
import dev.smallnext.app.progress.ProgressFlow
import dev.smallnext.app.progress.ServerAI
import dev.smallnext.app.progress.ServerAISettings
import dev.smallnext.app.progress.defaultSuggestionProvider
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async

class SmallnextApplication : Application() {
    val database: AppDatabase by lazy { AppDatabase.open(this) }

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private var openedFlow: Deferred<ProgressFlow>? = null

    /**
     * `android_core_flow` 경로에서만 연다. 진행 흐름과 대기 요청은 Activity가 아니라 앱 수명에 묶는다.
     * 처음 연 실행의 `android_server_ai`로 공급자를 고른다. 메인 스레드에서만 부른다.
     */
    fun progressFlow(flags: FeatureFlags): Deferred<ProgressFlow> = openedFlow ?: appScope.async {
        val server = ServerAI.provider(flags.serverAI, ServerAISettings.fromBuildConfig()) { url, key ->
            val file = File(File(filesDir, KeystoreSessionStore.DIRECTORY), "session")
            SupabaseAnonymousIdentity.create(url, key, KeystoreSessionStore(file))
        }
        ProgressFlow.open(database, server ?: defaultSuggestionProvider(), appScope)
    }.also { openedFlow = it }
}
