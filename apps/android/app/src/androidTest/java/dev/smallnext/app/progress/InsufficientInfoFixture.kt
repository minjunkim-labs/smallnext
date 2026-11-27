package dev.smallnext.app.progress

/**
 * 공유 계약 `contracts/fixtures/insufficient-info.json`의 문구다. iOS `InsufficientInfoFixture`와 같은 값을 쓴다.
 * 계기 테스트(androidTest)는 저장소 파일을 읽을 수 없어 값을 옮겨 둔다. JVM 테스트 `InsufficientInfoFixtureDriftTest`가 파일과 같은지 대조한다.
 * 값은 따옴표·역슬래시·개행 없이 한 줄 문자열 상수로 둔다. 대조가 이 형태를 전제로 읽는다.
 */
object InsufficientInfoFixture {
    /** `response.proposal.reason`이다. */
    const val REASON = "현재 제공된 정보로는 당시 역할을 확인할 수 없고, 유용한 중간 단계나 새로 물을 내용도 제시하기 어려워요."

    /** `question`이다. */
    const val QUESTION = "직접 확인할 수 있는 기록이 있나요?"

    /** `answer`다. */
    const val ANSWER = "모르고 확인할 자료도 없어요."
}
