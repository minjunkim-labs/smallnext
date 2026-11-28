package dev.smallnext.app.progress

/** JVM 테스트의 같은 이름 클래스와 같다. 두 소스 세트는 서로 보이지 않아 따로 둔다. */
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
