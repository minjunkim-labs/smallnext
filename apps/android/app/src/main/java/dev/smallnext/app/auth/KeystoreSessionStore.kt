package dev.smallnext.app.auth

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Android Keystore의 AES-GCM 키로 암호화한 앱 전용 파일이다.
 * 이 파일의 폴더(`files/auth/`)는 자동 백업과 기기 간 이전에서 제외한다(`res/xml`의 두 규칙).
 * 키가 없거나 복호화에 실패하면 예외를 던진다. 그러면 [SupabaseAnonymousIdentity]가 새 계정을 만들지 않는다.
 */
class KeystoreSessionStore(private val file: File, private val alias: String = ALIAS) : SessionStore {
    override fun read(): String? {
        val atomic = AtomicFile(file)
        if (!atomic.baseFile.exists()) return null
        val bytes = atomic.readFully()
        check(bytes.size > IV_BYTES) { "session file is truncated" }
        val key = keyStore().getKey(alias, null) as? SecretKey ?: error("session key is unavailable")
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, bytes, 0, IV_BYTES))
        return cipher.doFinal(bytes, IV_BYTES, bytes.size - IV_BYTES).toString(Charsets.UTF_8)
    }

    override fun write(value: String) {
        val key = keyStore().getKey(alias, null) as? SecretKey ?: generateKey()
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key)
        val data = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        check(cipher.iv.size == IV_BYTES)
        file.parentFile?.mkdirs()
        val atomic = AtomicFile(file)
        val output = atomic.startWrite()
        try {
            output.write(data)
            atomic.finishWrite(output)
        } catch (error: Exception) {
            atomic.failWrite(output)
            throw error
        }
    }

    override fun delete() = AtomicFile(file).delete()

    private fun generateKey(): SecretKey = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE).run {
        init(
            KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        generateKey()
    }

    companion object {
        const val ALIAS = "dev.smallnext.app.supabase-session"
        const val DIRECTORY = "auth"
        private const val KEYSTORE = "AndroidKeyStore"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val IV_BYTES = 12
        private const val TAG_BITS = 128

        private fun keyStore() = KeyStore.getInstance(KEYSTORE).apply { load(null) }
    }
}
