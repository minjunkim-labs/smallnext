package dev.smallnext.app.progress

import android.content.res.XmlResourceParser
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.R
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SharedPreferencesConsentStoreTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Before
    fun clean() {
        context.getSharedPreferences(SharedPreferencesConsentStore.FILE, 0).edit().clear().commit()
    }

    @After
    fun restore() = clean()

    /** 동의는 앱 전용 설정에 남고 다시 열어도 같다. 처음에는 동의하지 않은 상태다. */
    @Test
    fun consentPersistsInAppPrivatePreferencesAcrossInstances() {
        val consent = AIConsent(SharedPreferencesConsentStore(context))
        assertFalse(consent.state.value)
        assertTrue(consent.grant())
        assertTrue(AIConsent(SharedPreferencesConsentStore(context)).isGranted())
        assertTrue(consent.withdraw())
        assertFalse(AIConsent(SharedPreferencesConsentStore(context)).isGranted())
    }

    /** 동의는 클라우드 백업·기기 간 이전에 실려 가지 않는다. 다른 기기에서 동의한 것으로 보이면 안 된다. */
    @Test
    fun consentFileIsExcludedFromBackupAndDeviceTransfer() {
        val path = "${SharedPreferencesConsentStore.FILE}.xml"
        assertEquals(listOf("full-backup-content"), excludedSections(R.xml.backup_rules, path))
        assertEquals(listOf("cloud-backup", "device-transfer"), excludedSections(R.xml.data_extraction_rules, path))
    }

    private fun excludedSections(resource: Int, path: String): List<String> {
        val parser = context.resources.getXml(resource)
        val sections = mutableListOf<String>()
        var section = ""
        while (parser.next() != XmlResourceParser.END_DOCUMENT) {
            if (parser.eventType != XmlResourceParser.START_TAG) continue
            when (parser.name) {
                "exclude" -> if (parser.getAttributeValue(null, "domain") == "sharedpref" && parser.getAttributeValue(null, "path") == path) {
                    sections += section
                }
                else -> section = parser.name
            }
        }
        return sections
    }
}
