package dev.smallnext.app.progress

import com.google.gson.annotations.SerializedName

/**
 * 공급자가 근거 부족을 알린 마지막 안내다. iOS `InformationNotice`와 같은 값이다. 목표별로 하나만 저장한다.
 * [inputFingerprint]는 안내를 받은 요청의 입력 지문이다. 이 안내가 지금 입력에 대한 것인지는 지문을 다시 만들어 비교한다.
 */
data class InformationNotice(
    val requestId: Long,
    val requestKind: SuggestionKind,
    val goalRevision: Int,
    val inputFingerprint: String,
    val reason: String,
    /** 수신 시각이다. epoch 밀리초. */
    val receivedAt: Long,
    /** 안내를 받을 때 현재 행동이었던 행동이다. 없으면 null이다. */
    val currentActionId: Long?,
)

/**
 * 목표별 보충 맥락 메타데이터(`supplemental_context:<목표 ID>`)의 저장 형태다. 키 이름은 iOS `SupplementalContext`와 같다.
 * 이 단계는 마지막 안내만 담는다. 보충 입력의 확인값·초안(#357)은 같은 레코드에 더한다.
 */
internal data class StoredSupplementalContext(
    @SerializedName("last_notice") val lastNotice: StoredNotice? = null,
)

internal data class StoredNotice(
    @SerializedName("request_id") val requestId: Long,
    @SerializedName("request_kind") val requestKind: String,
    @SerializedName("goal_revision") val goalRevision: Int,
    @SerializedName("input_fingerprint") val inputFingerprint: String,
    @SerializedName("reason") val reason: String,
    @SerializedName("received_at") val receivedAt: Long,
    @SerializedName("current_action_id") val currentActionId: Long?,
) {
    /** 알 수 없는 요청 종류가 저장돼 있으면 null이다. 안내로 보이지 않는다. */
    fun toNotice(): InformationNotice? = SuggestionKind.of(requestKind)?.let {
        InformationNotice(requestId, it, goalRevision, inputFingerprint, reason, receivedAt, currentActionId)
    }
}
