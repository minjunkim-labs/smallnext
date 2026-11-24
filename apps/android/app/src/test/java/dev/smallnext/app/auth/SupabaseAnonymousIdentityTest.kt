package dev.smallnext.app.auth

import dev.smallnext.app.progress.SuggestionException
import dev.smallnext.app.progress.SuggestionFailure
import io.github.jan.supabase.auth.user.UserInfo
import io.github.jan.supabase.auth.user.UserSession
import java.util.Collections
import kotlin.time.Clock
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** iOS `UserServerAITests`의 신원 사례와 같은 결과를 가짜 Auth 전송과 가짜 저장소로 확인한다. 이름은 iOS 테스트 이름과 같다. */
class SupabaseAnonymousIdentityTest {
    @Test
    fun testConcurrentAnonymousSignInIsSharedAndSessionIsReused() = runBlocking {
        val f = fixture(delayMillis = 100)
        val tokens = listOf(async { f.identity.idToken() }, async { f.identity.idToken() }).awaitAll()
        assertEquals(listOf("synthetic-access", "synthetic-access"), tokens)
        assertEquals("synthetic-access", f.identity.idToken())
        assertEquals(listOf("/auth/v1/signup"), f.transport.paths)
        assertNotNull(f.store.value)
    }

    @Test
    fun testRestoredSessionRefreshesWithoutAnotherAnonymousSignUp() = runBlocking {
        val f = fixture(delayMillis = 100)
        f.store.value = StoreSessionManager.encode(session(expired = true))
        val tokens = listOf(async { f.identity.idToken() }, async { f.identity.idToken() }).awaitAll()
        assertEquals(listOf("synthetic-access", "synthetic-access"), tokens)
        assertEquals(listOf("/auth/v1/token"), f.transport.paths)
    }

    @Test
    fun testRefreshFailureDoesNotCreateAnotherAnonymousAccount() = runBlocking {
        val f = fixture(status = 401)
        f.store.value = StoreSessionManager.encode(session(expired = true))
        assertFailure(SuggestionFailure.UNAVAILABLE) { f.identity.idToken() }
        assertFailure(SuggestionFailure.UNAVAILABLE) { f.identity.idToken() }
        assertEquals(listOf("/auth/v1/token", "/auth/v1/token"), f.transport.paths)
    }

    @Test
    fun testAuthenticationFailureDoesNotRetry() = runBlocking {
        val f = fixture(status = 403, delayMillis = 100)
        val waiters = listOf(async { runCatching { f.identity.idToken() } }, async { runCatching { f.identity.idToken() } }).awaitAll()
        for (result in waiters) assertEquals(SuggestionFailure.UNAVAILABLE, (result.exceptionOrNull() as SuggestionException).failure)
        assertEquals(listOf("/auth/v1/signup"), f.transport.paths)
        // 사용자가 다시 요청했을 때만 한 번 더 보낸다.
        assertFailure(SuggestionFailure.UNAVAILABLE) { f.identity.idToken() }
        assertEquals(2, f.transport.paths.size)
    }

    @Test
    fun testCancellationDoesNotReturnTokenOrCancelAnotherWaiter() = runBlocking {
        val f = fixture(delayMillis = 200)
        val cancelled = async { f.identity.idToken() }
        repeat(100) { if (f.transport.paths.isEmpty()) delay(5) }
        cancelled.cancel()
        val other = async { f.identity.idToken() }
        try {
            cancelled.await()
            fail("must cancel")
        } catch (_: CancellationException) {
        }
        assertEquals("synthetic-access", other.await())
        assertEquals(listOf("/auth/v1/signup"), f.transport.paths)
    }

    @Test
    fun testStorageFailureNeverCreatesAccountOrReturnsUnpersistedToken() = runBlocking {
        for (readFailure in listOf(true, false)) {
            val f = fixture()
            f.store.failReads = readFailure
            f.store.failWrites = !readFailure
            assertFailure(SuggestionFailure.UNAVAILABLE) { f.identity.idToken() }
            assertEquals(if (readFailure) 0 else 1, f.transport.paths.size)
        }
    }

    /** Android 추가: 복호화는 됐지만 SDK가 읽지 못한 세션도 새 계정으로 바꾸지 않는다. */
    @Test
    fun unreadableStoredSessionNeverCreatesAccount() = runBlocking {
        val f = fixture()
        f.store.value = "not a session"
        assertFailure(SuggestionFailure.UNAVAILABLE) { f.identity.idToken() }
        assertTrue(f.transport.paths.isEmpty())
    }

    @Test
    fun testNonAnonymousSessionIsRejectedWithoutNetwork() = runBlocking {
        for (expired in listOf(false, true)) {
            val f = fixture()
            f.store.value = StoreSessionManager.encode(session(expired = expired, anonymous = false))
            assertFailure(SuggestionFailure.REJECTED) { f.identity.idToken() }
            assertTrue(f.transport.paths.isEmpty())
        }
    }

    /** 로컬 로그아웃은 이 기기의 세션만 지운다. 다음 요청은 새 익명 가입이다. */
    @Test
    fun localSignOutRemovesOnlyTheStoredSession() = runBlocking {
        val f = fixture()
        f.identity.idToken()
        f.identity.signOutLocally()
        assertNull(f.store.value)
        assertEquals(listOf("/auth/v1/signup", "/auth/v1/logout"), f.transport.paths)
        assertEquals("local", f.transport.logoutScope)
    }

    private suspend fun assertFailure(expected: SuggestionFailure, block: suspend () -> Unit) {
        try {
            block()
            fail("must fail with $expected")
        } catch (error: SuggestionException) {
            assertEquals(expected, error.failure)
        }
    }

    private fun session(expired: Boolean = false, anonymous: Boolean = true) = UserSession(
        accessToken = "synthetic-old",
        refreshToken = "synthetic-refresh",
        expiresIn = 3600,
        tokenType = "bearer",
        user = UserInfo(aud = "authenticated", id = "00000000-0000-0000-0000-000000000001", isAnonymous = anonymous),
        expiresAt = Clock.System.now() + (if (expired) -60 else 3600).seconds,
    )

    private class Fixture(val identity: SupabaseAnonymousIdentity, val transport: AuthTransport, val store: MemoryStore)

    private fun fixture(status: Int = 200, delayMillis: Long = 0): Fixture {
        val transport = AuthTransport(status, delayMillis)
        val store = MemoryStore()
        val client = OkHttpClient.Builder().addInterceptor(transport).build()
        return Fixture(SupabaseAnonymousIdentity.create("https://auth.example.invalid", "sb_publishable_synthetic", store, client), transport, store)
    }

    private class AuthTransport(private val status: Int, private val delayMillis: Long) : Interceptor {
        val paths: MutableList<String> = Collections.synchronizedList(mutableListOf())

        @Volatile var logoutScope: String? = null

        override fun intercept(chain: Interceptor.Chain): Response {
            val request = chain.request()
            paths += request.url.encodedPath
            if (request.url.encodedPath == "/auth/v1/logout") {
                logoutScope = request.url.queryParameter("scope")
                return response(chain, 204, "")
            }
            if (delayMillis > 0) Thread.sleep(delayMillis)
            val body = if (status == 200) {
                """{"access_token":"synthetic-access","token_type":"bearer","expires_in":3600,"refresh_token":"synthetic-refresh-new",""" +
                    """"user":{"id":"00000000-0000-0000-0000-000000000001","aud":"authenticated","is_anonymous":true}}"""
            } else {
                """{"msg":"synthetic rejection","error_code":"invalid_credentials"}"""
            }
            return response(chain, status, body)
        }

        private fun response(chain: Interceptor.Chain, code: Int, body: String) = Response.Builder()
            .request(chain.request())
            .protocol(Protocol.HTTP_1_1)
            .code(code)
            .message("synthetic")
            .body(body.toResponseBody("application/json".toMediaType()))
            .build()
    }

    private class MemoryStore : SessionStore {
        @Volatile var value: String? = null

        @Volatile var failReads = false

        @Volatile var failWrites = false

        override fun read(): String? {
            if (failReads) error("synthetic read failure")
            return value
        }

        override fun write(value: String) {
            if (failWrites) error("synthetic write failure")
            this.value = value
        }

        override fun delete() {
            value = null
        }
    }
}
