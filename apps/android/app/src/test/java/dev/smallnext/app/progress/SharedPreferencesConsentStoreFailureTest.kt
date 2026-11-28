package dev.smallnext.app.progress

import android.content.SharedPreferences
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `SharedPreferences.commit()`은 디스크 쓰기가 실패해도 메모리 값을 바꿔 둔다. 그래서 저장하지 못한 동의가
 * 요청 게이트에서는 동의로 읽히거나 철회가 안 된 채 막히지 않는지 확인한다.
 */
class SharedPreferencesConsentStoreFailureTest {
    @Test
    fun failedGrantDoesNotLeaveConsentGranted() {
        val preferences = FailingPreferences()
        val store = SharedPreferencesConsentStore(preferences)
        val consent = AIConsent(store)
        preferences.failing = true
        assertFalse(consent.grant())
        assertFalse(consent.state.value)
        assertFalse(store.read())
        assertFalse(consent.isGranted())
    }

    @Test
    fun failedWithdrawalKeepsConsentGrantedForStateAndProvider() {
        val preferences = FailingPreferences()
        val consent = AIConsent(SharedPreferencesConsentStore(preferences))
        assertTrue(consent.grant())
        preferences.failing = true
        assertFalse(consent.withdraw())
        assertTrue(consent.state.value)
        assertTrue(consent.isGranted())
        // 쓰기가 되돌아오면 다시 저장된다.
        preferences.failing = false
        assertTrue(consent.withdraw())
        assertFalse(consent.isGranted())
    }
}

/** 메모리 값을 먼저 바꾸고 디스크 쓰기에서 실패하는 AOSP `SharedPreferencesImpl`의 동작을 흉내 낸다. */
private class FailingPreferences : SharedPreferences {
    var failing = false
    val values = mutableMapOf<String?, Any?>()

    override fun getAll(): MutableMap<String, *> = mutableMapOf<String, Any?>()
    override fun getString(key: String?, defValue: String?): String? = values[key] as? String ?: defValue
    override fun getStringSet(key: String?, defValues: MutableSet<String>?): MutableSet<String>? = defValues
    override fun getInt(key: String?, defValue: Int): Int = values[key] as? Int ?: defValue
    override fun getLong(key: String?, defValue: Long): Long = values[key] as? Long ?: defValue
    override fun getFloat(key: String?, defValue: Float): Float = values[key] as? Float ?: defValue
    override fun getBoolean(key: String?, defValue: Boolean): Boolean = values[key] as? Boolean ?: defValue
    override fun contains(key: String?): Boolean = values.containsKey(key)
    override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit
    override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit

    override fun edit(): SharedPreferences.Editor = FailingEditor(this)
}

private class FailingEditor(private val preferences: FailingPreferences) : SharedPreferences.Editor {
    private val pending = mutableMapOf<String?, Any?>()

    private fun put(key: String?, value: Any?): SharedPreferences.Editor {
        pending[key] = value
        return this
    }

    override fun putString(key: String?, value: String?) = put(key, value)
    override fun putStringSet(key: String?, values: MutableSet<String>?) = put(key, values)
    override fun putInt(key: String?, value: Int) = put(key, value)
    override fun putLong(key: String?, value: Long) = put(key, value)
    override fun putFloat(key: String?, value: Float) = put(key, value)
    override fun putBoolean(key: String?, value: Boolean) = put(key, value)

    override fun remove(key: String?): SharedPreferences.Editor {
        pending.remove(key)
        return this
    }

    override fun clear(): SharedPreferences.Editor {
        pending.clear()
        return this
    }

    override fun commit(): Boolean {
        preferences.values.putAll(pending)
        return !preferences.failing
    }

    // `apply()`는 메모리를 바로 바꾸고 디스크 쓰기는 비동기로 한다.
    override fun apply() {
        preferences.values.putAll(pending)
    }
}
