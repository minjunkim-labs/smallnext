package dev.smallnext.app.progress

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** 동의 값을 담는 앱 전용 저장소다. [write]는 저장에 성공했을 때만 true다. */
interface ConsentStore {
    fun read(): Boolean
    fun write(granted: Boolean): Boolean
}

/**
 * 서버 AI로 목표·자료를 보내기 전의 명시 동의다(iOS `AIConsent`). 동의 값은 앱 전용 설정에만 둔다.
 * [state]는 화면이 보는 값이고, 요청마다의 확인은 저장한 값을 다시 읽는다([isGranted]).
 * 저장에 실패하면 값을 바꾸지 않는다. 동의했다고 보이는데 저장되지 않은 상태를 만들지 않는다.
 */
class AIConsent(private val store: ConsentStore) {
    private val _state = MutableStateFlow(store.read())
    val state: StateFlow<Boolean> = _state.asStateFlow()

    fun isGranted(): Boolean = store.read()

    fun grant(): Boolean = set(true)

    fun withdraw(): Boolean = set(false)

    private fun set(granted: Boolean): Boolean {
        if (!store.write(granted)) return false
        _state.value = granted
        return true
    }
}

/** 동의 값은 SharedPreferences 한 값에 둔다. 백업·기기 간 이전에서는 뺀다(`backup_rules.xml`, `data_extraction_rules.xml`). */
class SharedPreferencesConsentStore(private val preferences: SharedPreferences) : ConsentStore {
    constructor(context: Context) : this(context.getSharedPreferences(FILE, Context.MODE_PRIVATE))

    override fun read(): Boolean = preferences.getBoolean(KEY, false)

    override fun write(granted: Boolean): Boolean {
        val previous = read()
        if (preferences.edit().putBoolean(KEY, granted).commit()) return true
        // commit()은 디스크 쓰기가 실패해도 메모리 값을 이미 바꾼 채 둔다. 저장하지 못한 값을 요청 게이트가 읽지 않도록 되돌린다.
        preferences.edit().putBoolean(KEY, previous).apply()
        return false
    }

    companion object {
        /** 파일 이름은 백업 제외 규칙과 같아야 한다. */
        const val FILE = "smallnext_consent"
        const val KEY = "ai_transfer_consent"
    }
}

/** 동의가 없으면 서버로 보내지 않는다. 화면 게이트와 별개로 요청마다 다시 확인한다(iOS `ConsentGatedProvider`). */
class ConsentGatedProvider(
    private val base: ActionSuggestionProvider,
    private val consent: AIConsent,
) : ActionSuggestionProvider {
    override suspend fun suggest(request: SuggestionRequest): SuggestionCandidate {
        if (!consent.isGranted()) throw SuggestionException(SuggestionFailure.UNAVAILABLE)
        return base.suggest(request)
    }
}
