package dev.smallnext.app.auth

import android.content.res.XmlResourceParser
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.R
import dev.smallnext.app.progress.SuggestionException
import dev.smallnext.app.progress.SuggestionFailure
import java.io.File
import java.security.KeyStore
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith

/** iOS `testSDKSessionStorageUsesProtectedNonSynchronizingKeychain` 대응. Android Keystore로 암호화한 앱 전용 파일을 확인한다. */
@RunWith(AndroidJUnit4::class)
class KeystoreSessionStoreTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val alias = "dev.smallnext.app.auth-test.${UUID.randomUUID()}"
    private val directory = File(context.filesDir, "auth-test-${UUID.randomUUID()}")
    private val file = File(directory, "session")
    private val store = KeystoreSessionStore(file, alias)

    @After
    fun cleanUp() {
        directory.deleteRecursively()
        keyStore().deleteEntry(alias)
    }

    @Test
    fun sessionIsEncryptedWithAKeystoreKey() {
        assertNull(store.read())
        store.write("synthetic-session")
        assertEquals("synthetic-session", store.read())
        assertFalse(String(file.readBytes(), Charsets.ISO_8859_1).contains("synthetic-session"))
        assertTrue(keyStore().containsAlias(alias))
        store.delete()
        assertNull(store.read())
    }

    /** Android 10 이하의 AtomicFile은 쓰는 동안 원본을 `.bak`으로 옮긴다. 그때 끊긴 세션도 읽는다. */
    @Test
    fun interruptedWriteBackupIsRestored() {
        store.write("synthetic-session")
        assertTrue(file.renameTo(File(directory, "session.bak")))
        assertEquals("synthetic-session", store.read())
    }

    @Test
    fun missingKeyOrTamperedFileBlocksAuthenticationWithoutSignUp() = runBlocking {
        store.write("synthetic-session")
        val bytes = file.readBytes()
        bytes[bytes.size - 1] = (bytes.last().toInt() xor 1).toByte()
        file.writeBytes(bytes)
        assertBlocked()

        store.write("synthetic-session")
        keyStore().deleteEntry(alias)
        assertBlocked()
    }

    private suspend fun assertBlocked() {
        try {
            store.read()
            fail("an unreadable session must fail")
        } catch (_: Exception) {
        }
        val requests = AtomicInteger()
        val client = OkHttpClient.Builder().addInterceptor(Interceptor { requests.incrementAndGet(); error("no network") }).build()
        val identity = SupabaseAnonymousIdentity.create("https://auth.example.invalid", "sb_publishable_synthetic", store, client)
        try {
            identity.idToken()
            fail("must fail closed")
        } catch (error: SuggestionException) {
            assertEquals(SuggestionFailure.UNAVAILABLE, error.failure)
        }
        assertEquals(0, requests.get())
    }

    /** 세션 폴더는 자동 백업(Android 11 이하)과 클라우드 백업·기기 간 이전(Android 12 이상)에서 빠진다. */
    @Test
    fun sessionDirectoryIsExcludedFromBackupAndDeviceTransfer() {
        val path = "${KeystoreSessionStore.DIRECTORY}/"
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
                "exclude" -> if (parser.getAttributeValue(null, "domain") == "file" && parser.getAttributeValue(null, "path") == path) {
                    sections += section
                }
                else -> section = parser.name
            }
        }
        return sections
    }

    private fun keyStore() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
}
