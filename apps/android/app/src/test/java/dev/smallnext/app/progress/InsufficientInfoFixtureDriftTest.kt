package dev.smallnext.app.progress

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 계기 테스트가 쓰는 `InsufficientInfoFixture` 상수가 공유 계약 파일과 같은지 확인한다.
 * 계기 테스트는 저장소 파일을 읽을 수 없어 값을 옮겨 두므로, 계약 문구가 바뀌면 여기서 먼저 깨진다.
 */
class InsufficientInfoFixtureDriftTest {
    private fun repository(): File {
        var dir: File? = File(System.getProperty("user.dir")!!).absoluteFile
        while (dir != null && !File(dir, "contracts/fixtures").isDirectory) dir = dir.parentFile
        return dir ?: error("저장소 루트를 찾지 못했다")
    }

    private fun shared(): JsonObject = JsonParser.parseString(File(repository(), "contracts/fixtures/insufficient-info.json").readText()).asJsonObject

    private fun constants(): Map<String, String> {
        val source = File(repository(), "apps/android/app/src/androidTest/java/dev/smallnext/app/progress/InsufficientInfoFixture.kt").readText()
        return Regex("""const val (\w+) = "([^"\\\n]*)"""").findAll(source).associate { it.groupValues[1] to it.groupValues[2] }
    }

    @Test
    fun testAndroidTestFixtureConstantsMatchTheSharedContract() {
        val shared = shared()
        val constants = constants()
        assertEquals(setOf("REASON", "QUESTION", "ANSWER"), constants.keys)
        assertEquals(shared["response"].asJsonObject["proposal"].asJsonObject["reason"].asString, constants["REASON"])
        assertEquals(shared["question"].asString, constants["QUESTION"])
        assertEquals(shared["answer"].asString, constants["ANSWER"])
        assertTrue(constants.values.all { it.isNotBlank() })
    }
}
