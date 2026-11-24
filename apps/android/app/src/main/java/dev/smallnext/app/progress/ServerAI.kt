package dev.smallnext.app.progress

import dev.smallnext.app.BuildConfig
import dev.smallnext.app.auth.SupabaseAnonymousIdentity
import java.net.URI

/** Git 밖 Gradle 설정(`SMALLNEXT_*`)이 빌드 값으로 넣은 공개 client 설정이다. 없으면 빈 문자열이다. */
data class ServerAISettings(
    val apiBaseUrl: String,
    val supabaseUrl: String,
    val publishableKey: String,
    val privacyPolicyUrl: String,
    val captchaUrl: String = "",
    val turnstileSiteKey: String = "",
) {
    companion object {
        fun fromBuildConfig() = ServerAISettings(
            BuildConfig.API_BASE_URL, BuildConfig.SUPABASE_URL, BuildConfig.SUPABASE_PUBLISHABLE_KEY,
            BuildConfig.PRIVACY_POLICY_URL, BuildConfig.AUTH_CAPTCHA_URL, BuildConfig.TURNSTILE_SITE_KEY,
        )
    }
}

/** `android_server_ai`로 사용자 서버 공급자를 고른다. iOS `UserServerAI.configured`와 같은 검사다. iOS `user_server_ai`는 읽지 않는다. */
object ServerAI {
    private val publishableKey = Regex("^sb_publishable_[A-Za-z0-9_-]+$")

    /**
     * OFF면 null이다. 호출한 쪽이 빌드별 기본 공급자(Debug 고정, Release `사용 불가`)를 쓴다.
     * 설정이 없거나 잘못되면 [identity]를 부르지 않고 `사용 불가` 공급자를 돌려준다.
     */
    fun provider(
        enabled: Boolean,
        settings: ServerAISettings,
        identity: (projectUrl: String, publishableKey: String) -> SupabaseAnonymousIdentity,
    ): ActionSuggestionProvider? {
        if (!enabled) return null
        fun value(text: String) = text.takeIf { it.isNotEmpty() && it.none(Char::isWhitespace) }
        val api = value(settings.apiBaseUrl)?.takeIf(ServerSuggestionProvider::endpoint)
        val project = value(settings.supabaseUrl)?.takeIf(ServerSuggestionProvider::endpoint)
        val key = value(settings.publishableKey)?.takeIf(publishableKey::matches)
        // Android는 CAPTCHA 화면이 없다. CAPTCHA 설정이 하나라도 있으면 Auth client를 만들지 않는다.
        val captcha = settings.captchaUrl.isNotEmpty() || settings.turnstileSiteKey.isNotEmpty()
        if (api == null || project == null || key == null || !privacyPolicy(settings.privacyPolicyUrl) || captcha) {
            return UnavailableSuggestionProvider
        }
        return ServerSuggestionProvider.create(api, identity(project, key)::idToken)
    }

    /** 사용자 정보가 없는 https 처리방침 주소만 받는다. iOS `AIConsent.privacyPolicyURL`과 같다. */
    fun privacyPolicy(address: String): Boolean = try {
        val uri = URI(address)
        address.none(Char::isWhitespace) && uri.scheme?.lowercase() == "https" && !uri.host.isNullOrEmpty() && uri.rawUserInfo == null
    } catch (_: Exception) {
        false
    }
}
