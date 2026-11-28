package dev.smallnext.app.progress

import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** iOS `AIConsentTests`에 대응하는 JVM 테스트다. 화면과 저장소 연결은 계측 테스트가 확인한다. */
class AIConsentTest {
    /** iOS `testPrivacyPolicyURLAcceptsOnlyHTTPSPages`. */
    @Test
    fun testPrivacyPolicyURLAcceptsOnlyHTTPSPages() {
        assertTrue(ServerAI.privacyPolicy("https://example.invalid/privacy"))
        for (value in listOf(
            "", "$(SMALLNEXT_PRIVACY_POLICY_URL)", "http://example.invalid/privacy", "https://user:password@example.invalid/privacy",
            "https://user@example.invalid/privacy", "privacy", "https:///privacy", "HTTP://example.invalid/privacy",
            "https://example.invalid/privacy page", " https://example.invalid/privacy", "ftp://example.invalid/privacy",
        )) {
            assertFalse(value, ServerAI.privacyPolicy(value))
        }
        // 대소문자를 가리지 않는 https만 받는다.
        assertTrue(ServerAI.privacyPolicy("HTTPS://example.invalid/privacy"))
    }

    /** iOS `testProviderSendsOnlyWhileConsentIsGranted`. 요청마다 저장한 동의를 다시 확인한다. */
    @Test
    fun testProviderSendsOnlyWhileConsentIsGranted() = runBlocking {
        val store = MemoryConsentStore()
        val consent = AIConsent(store)
        val base = CountingProvider()
        val provider = ConsentGatedProvider(base, consent)
        val request = SuggestionRequest(SuggestionKind.FIRST_ACTION, "정리")
        // 화면 상태가 아니라 저장한 값을 요청마다 읽는다. 저장소를 바로 바꿔도 다음 요청부터 따른다.
        for (granted in listOf(null, true, false)) {
            if (granted != null) store.value = granted
            try {
                provider.suggest(request)
                assertEquals(true, granted)
            } catch (error: SuggestionException) {
                assertTrue(granted != true)
                assertEquals(SuggestionFailure.UNAVAILABLE, error.failure)
            }
        }
        assertEquals(1, base.calls.get())
    }

    @Test
    fun consentStartsWithdrawnAndFollowsGrantAndWithdraw() {
        val store = MemoryConsentStore()
        val consent = AIConsent(store)
        assertFalse(consent.state.value)
        assertFalse(consent.isGranted())
        assertTrue(consent.grant())
        assertTrue(consent.state.value)
        assertTrue(store.value)
        // 앱을 다시 열면 저장한 동의를 읽는다.
        assertTrue(AIConsent(store).state.value)
        assertTrue(consent.withdraw())
        assertFalse(consent.state.value)
        assertFalse(AIConsent(store).state.value)
    }

    /** 저장하지 못하면 동의했다고 보이는 상태를 만들지 않는다. 철회를 저장하지 못하면 동의가 그대로라고 알린다. */
    @Test
    fun consentDoesNotChangeWhenStoringFails() = runBlocking {
        val store = MemoryConsentStore()
        val consent = AIConsent(store)
        val base = CountingProvider()
        val provider = ConsentGatedProvider(base, consent)
        store.failing = true
        assertFalse(consent.grant())
        assertFalse(consent.state.value)
        assertNull(runCatching { provider.suggest(SuggestionRequest(SuggestionKind.FIRST_ACTION, "정리")) }.getOrNull())
        store.failing = false
        assertTrue(consent.grant())
        store.failing = true
        assertFalse(consent.withdraw())
        assertTrue(consent.state.value)
        assertTrue(consent.isGranted())
        provider.suggest(SuggestionRequest(SuggestionKind.FIRST_ACTION, "정리"))
        assertEquals(1, base.calls.get())
    }

    private class CountingProvider : ActionSuggestionProvider {
        val calls = AtomicInteger()
        override suspend fun suggest(request: SuggestionRequest): SuggestionCandidate {
            calls.incrementAndGet()
            return SuggestionCandidate.NoAction
        }
    }
}

/** 메모리에 값을 둔다. [failing]이면 쓰기가 실패한다. */
class MemoryConsentStore : ConsentStore {
    @Volatile var value = false
    @Volatile var failing = false

    override fun read() = value

    override fun write(granted: Boolean): Boolean {
        if (failing) return false
        value = granted
        return true
    }
}
