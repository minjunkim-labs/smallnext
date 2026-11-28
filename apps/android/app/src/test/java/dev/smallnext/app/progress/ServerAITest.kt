package dev.smallnext.app.progress

import dev.smallnext.app.FeatureFlags
import dev.smallnext.app.auth.SessionStore
import dev.smallnext.app.auth.SupabaseAnonymousIdentity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** iOS `UserServerAITests.testInvalidSettingsAndOffFlagNeverCreateIdentity`와 같은 결과를 확인한다. */
class ServerAITest {
    private val valid = ServerAISettings(
        apiBaseUrl = "https://api.example.invalid",
        supabaseUrl = "https://project.example.invalid",
        publishableKey = "sb_publishable_synthetic",
        privacyPolicyUrl = "https://example.invalid/privacy",
    )
    private var creations = 0

    private fun provider(enabled: Boolean, settings: ServerAISettings) = ServerAI.provider(enabled, settings) { url, key ->
        creations += 1
        SupabaseAnonymousIdentity.create(url, key, EmptyStore)
    }

    @Test
    fun testInvalidSettingsAndOffFlagNeverCreateIdentity() = runBlocking {
        val cases = mutableListOf<ServerAISettings>()
        for (value in listOf("", " ", "https://example.invalid ")) {
            cases += valid.copy(apiBaseUrl = value)
            cases += valid.copy(supabaseUrl = value)
            cases += valid.copy(publishableKey = value)
            cases += valid.copy(privacyPolicyUrl = value)
        }
        for (value in listOf("http://example.invalid", "https://user:password@example.invalid", "https://example.invalid/path")) {
            cases += valid.copy(apiBaseUrl = value)
            cases += valid.copy(supabaseUrl = value)
        }
        cases += valid.copy(privacyPolicyUrl = "http://example.invalid/privacy")
        cases += valid.copy(privacyPolicyUrl = "https://user@example.invalid/privacy")
        cases += valid.copy(publishableKey = "sb_secret_invalid")
        // Android는 CAPTCHA를 지원하지 않는다. 설정이 하나라도 있으면 iOS와 달리 Auth client를 만들지 않는다.
        cases += valid.copy(captchaUrl = "https://captcha.example.invalid")
        cases += valid.copy(turnstileSiteKey = "synthetic-site")
        cases += valid.copy(captchaUrl = "https://captcha.example.invalid", turnstileSiteKey = "synthetic-site")
        for (settings in cases) {
            val provider = provider(true, settings)
            assertSame(settings.toString(), UnavailableSuggestionProvider, provider)
            try {
                provider!!.suggest(SuggestionRequest(SuggestionKind.FIRST_ACTION, "정리"))
                error("invalid settings must stay unavailable")
            } catch (error: SuggestionException) {
                assertEquals(SuggestionFailure.UNAVAILABLE, error.failure)
            }
        }
        assertEquals(0, creations)
        assertNull(provider(false, valid))
        assertEquals(0, creations)
        assertTrue(provider(true, valid) is ServerSuggestionProvider)
        assertEquals(1, creations)
    }

    /** `android_server_ai`만 공급자를 고른다. iOS `user_server_ai` 값과 무관하다. */
    @Test
    fun serverAIFollowsOnlyTheAndroidFlag() {
        fun registry(android: Boolean, ios: Boolean) =
            """{"version":1,"flags":[{"key":"android_server_ai","default":$android},{"key":"user_server_ai","default":$ios}]}"""
        for (ios in listOf(true, false)) {
            assertFalse(FeatureFlags.resolve(registry(android = false, ios = ios), emptyMap(), debug = false).serverAI)
            assertTrue(FeatureFlags.resolve(registry(android = true, ios = !ios), emptyMap(), debug = false).serverAI)
        }
        assertNull(provider(FeatureFlags.resolve(registry(android = false, ios = true), emptyMap(), debug = true).serverAI, valid))
        assertEquals(0, creations)
    }

    private object EmptyStore : SessionStore {
        override fun read(): String? = null
        override fun write(value: String) = Unit
        override fun delete() = Unit
    }
}
