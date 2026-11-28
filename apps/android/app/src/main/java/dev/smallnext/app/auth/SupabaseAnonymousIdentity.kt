package dev.smallnext.app.auth

import dev.smallnext.app.progress.SuggestionException
import dev.smallnext.app.progress.SuggestionFailure
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.auth.MemoryCodeVerifierCache
import io.github.jan.supabase.auth.SessionManager
import io.github.jan.supabase.auth.SignOutScope
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.exception.NoSessionFoundException
import io.github.jan.supabase.auth.user.UserSession
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.logging.LogLevel
import io.ktor.client.engine.okhttp.OkHttp
import kotlin.time.Clock
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient

/** 세션 하나를 담는 저장소다. 없으면 null이다. 읽기·쓰기·지우기에 실패하면 예외를 던진다. */
interface SessionStore {
    fun read(): String?

    /** 새 계정을 만들기 전에 부른다. 저장할 수 없으면(예: Keystore 키를 만들 수 없음) 예외를 던진다. */
    fun prepare() = Unit
    fun write(value: String)
    fun delete()
}

/** SDK 기본 저장소 대신 앱이 주입한 [SessionStore]에 세션을 둔다. */
internal class StoreSessionManager(private val store: SessionStore) : SessionManager {
    /** 로컬 로그아웃 중에만 true다. */
    @Volatile var deleteAllowed = false

    override suspend fun saveSession(session: UserSession) = store.write(encode(session))

    override suspend fun loadSession(): UserSession = store.read()?.let(::decode) ?: throw NoSessionFoundException()

    /**
     * SDK는 갱신 거부(`session_not_found`)에도 세션을 지운다. 그러면 다음 요청이 새 계정을 만든다.
     * 그래서 로컬 로그아웃이 아닌 삭제는 무시한다. 저장한 세션이 남아 다음 요청도 갱신만 시도한다.
     */
    override suspend fun deleteSession() {
        if (deleteAllowed) store.delete()
    }

    companion object {
        // 만료 시각은 기본값이 아니라 저장한 값으로 복원해야 한다.
        private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

        fun encode(session: UserSession) = json.encodeToString(UserSession.serializer(), session)

        fun decode(value: String) = json.decodeFromString(UserSession.serializer(), value)
    }
}

/**
 * 사용자 서버에 보낼 Supabase 익명 계정의 access token을 얻는다. iOS `SupabaseAnonymousIdentity.idToken`과 같은 규칙이다.
 * SDK에서 쓰는 기능은 넷뿐이다: 익명 가입, 요청할 때의 세션 갱신(자동 갱신 OFF), 현재 사용자 조회, 로컬 로그아웃.
 * 토큰·UID·세션 값은 로그에 남기지 않는다.
 */
class SupabaseAnonymousIdentity internal constructor(
    private val auth: Auth,
    private val store: SessionStore,
    private val sessions: StoreSessionManager,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
) {
    private val lock = Any()

    /** 가입·갱신과 로컬 로그아웃을 차례로 실행한다. 로그아웃 뒤에 진행 중이던 가입이 세션을 다시 저장하지 않게 한다. */
    private val serial = Mutex()
    private var pending: Deferred<String>? = null

    /** 동시 요청은 한 번의 가입·갱신을 함께 기다린다. 기다리던 호출이 취소돼도 다른 대기자의 작업은 계속된다. */
    suspend fun idToken(): String {
        currentCoroutineContext().ensureActive()
        val task = synchronized(lock) {
            pending ?: scope.async { serial.withLock { obtain() } }.also { task ->
                pending = task
                task.invokeOnCompletion { synchronized(lock) { if (pending === task) pending = null } }
            }
        }
        val token = try {
            task.await()
        } catch (error: Exception) {
            currentCoroutineContext().ensureActive()
            throw (error as? SuggestionException) ?: SuggestionException(SuggestionFailure.UNAVAILABLE)
        }
        // 취소한 호출에는 토큰을 돌려주지 않는다.
        currentCoroutineContext().ensureActive()
        return token
    }

    /** 이 기기의 세션만 지운다. 계정 삭제(#360)가 서버 삭제 뒤에 부른다. */
    suspend fun signOutLocally() = serial.withLock {
        sessions.deleteAllowed = true
        try {
            auth.signOut(SignOutScope.LOCAL)
        } finally {
            sessions.deleteAllowed = false
        }
    }

    private suspend fun obtain(): String {
        // SDK는 저장소 읽기 실패를 세션 없음으로 본다. 저장소를 읽지 못하면 새 계정을 만들지 않는다.
        val stored = store.read()
        if (stored != null && auth.currentSessionOrNull() == null) auth.loadFromStorage(autoRefresh = false)
        if (auth.currentSessionOrNull() == null) {
            // 저장한 값이 있는데 SDK가 읽지 못했으면 다른 계정을 만들지 않는다.
            if (stored != null) throw SuggestionException(SuggestionFailure.UNAVAILABLE)
            // 가입 응답을 받은 뒤에는 저장 실패를 되돌릴 수 없다. 키를 쓸 수 없으면 가입하지 않는다.
            store.prepare()
            auth.signInAnonymously()
        }
        if (auth.currentUserOrNull()?.isAnonymous != true) throw SuggestionException(SuggestionFailure.REJECTED)
        val current = auth.currentSessionOrNull() ?: throw SuggestionException(SuggestionFailure.UNAVAILABLE)
        if (current.expiresAt - Clock.System.now() < REFRESH_MARGIN) auth.refreshCurrentSession()
        if (auth.currentUserOrNull()?.isAnonymous != true) throw SuggestionException(SuggestionFailure.REJECTED)
        val session = auth.currentSessionOrNull() ?: throw SuggestionException(SuggestionFailure.UNAVAILABLE)
        // 저장에 실패했거나 바뀐 세션의 토큰은 돌려주지 않는다.
        val persisted = store.read()?.let(StoreSessionManager::decode)
        if (persisted?.accessToken != session.accessToken) throw SuggestionException(SuggestionFailure.UNAVAILABLE)
        return session.accessToken
    }

    companion object {
        private val REFRESH_MARGIN = 60.seconds

        /** [projectUrl]과 [publishableKey]는 [dev.smallnext.app.progress.ServerAI]가 검증한 값이다. */
        fun create(
            projectUrl: String,
            publishableKey: String,
            store: SessionStore,
            client: OkHttpClient = OkHttpClient(),
        ): SupabaseAnonymousIdentity {
            val sessions = StoreSessionManager(store)
            val supabase = createSupabaseClient(projectUrl, publishableKey) {
                // SDK의 debug 로그는 세션(토큰 포함)을 출력한다.
                defaultLogLevel = LogLevel.NONE
                httpEngine = OkHttp.create {
                    preconfigured = client.newBuilder()
                        .followRedirects(false)
                        .followSslRedirects(false)
                        .retryOnConnectionFailure(false)
                        .build()
                }
                install(Auth) {
                    alwaysAutoRefresh = false
                    autoLoadFromStorage = false
                    enableLifecycleCallbacks = false
                    sessionManager = sessions
                    codeVerifierCache = MemoryCodeVerifierCache()
                }
            }
            return SupabaseAnonymousIdentity(supabase.auth, store, sessions)
        }
    }
}
