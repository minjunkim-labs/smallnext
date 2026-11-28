package dev.smallnext.app.progress

import androidx.annotation.StringRes
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.smallnext.app.R
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * AI 전송 동의 화면이다(iOS `AIConsentView`). 동의하기 전에는 이 화면만 나오고 AI로 아무것도 보내지 않는다.
 * 기기에 목표나 작성 중인 입력이 있으면 동의 없이도 모두 지울 수 있다. 진행 규칙은 [ProgressFlow]에 있다.
 */
@Composable
internal fun AIConsentScreen(flow: ProgressFlow, consent: AIConsent, privacyPolicyUrl: String?) {
    val state by flow.state.collectAsState()
    AIConsentContent(
        hasLocalData = state.goals.isNotEmpty() || state.goalInput != GoalInput(),
        privacyPolicyUrl = privacyPolicyUrl,
        agree = consent::grant,
        deleteLocalData = { flow.deleteAllGoals(confirmed = true) },
    )
}

/** [agree]는 동의를 저장하지 못하면 false를 돌려준다. 그때는 동의 화면에 남고 저장 실패를 알린다. */
@Composable
internal fun AIConsentContent(
    hasLocalData: Boolean,
    privacyPolicyUrl: String?,
    agree: () -> Boolean,
    deleteLocalData: suspend () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var confirming by rememberSaveable { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    // 결과 문구의 문자열 리소스다. 같은 문구가 이어져도 초점을 다시 옮기도록 번호를 함께 올린다.
    var message by rememberSaveable { mutableStateOf(0) }
    var messageSerial by rememberSaveable { mutableStateOf(0) }
    val messageFocus = remember { FocusRequester() }
    fun show(resource: Int) {
        message = resource
        messageSerial += 1
    }
    LaunchedEffect(messageSerial) {
        // 알림이 닫히는 동안의 안내는 TalkBack이 놓칠 수 있어 결과 문구로 초점을 옮긴다. 알림이 사라진 뒤 한 프레임을 기다려 요청한다.
        if (messageSerial > 0) {
            withFrameNanos {}
            messageFocus.requestFocus()
        }
    }
    Column(
        Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(24.dp),
        Arrangement.spacedBy(16.dp),
    ) {
        Heading(R.string.ai_consent_title, MaterialTheme.typography.titleLarge)
        Text(stringResource(R.string.ai_consent_sending), style = MaterialTheme.typography.bodyLarge)
        Text(stringResource(R.string.ai_consent_anonymous), style = MaterialTheme.typography.bodyLarge)
        Text(stringResource(R.string.ai_consent_required), style = MaterialTheme.typography.bodyLarge)
        if (privacyPolicyUrl != null) PrivacyPolicyLink(privacyPolicyUrl)
        CommandButton(
            R.string.ai_consent_agree,
            enabled = !deleting,
            clickLabel = stringResource(R.string.ai_consent_agree_hint),
        ) { if (!agree()) show(R.string.storage_failed) }
        if (hasLocalData) {
            DestructiveButton(R.string.delete_device_data, enabled = !deleting) { confirming = true }
        }
        if (deleting) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(24.dp))
                Text(stringResource(R.string.deleting), style = MaterialTheme.typography.bodyLarge)
            }
        }
        if (message != 0) {
            Text(stringResource(message), Modifier.focusRequester(messageFocus).focusable(), style = MaterialTheme.typography.bodyLarge)
        }
    }
    if (confirming) {
        AlertDialog(
            onDismissRequest = { confirming = false },
            title = { Text(stringResource(R.string.delete_device_data_title)) },
            // 큰 글꼴에서 메시지가 잘리지 않게 스크롤한다.
            text = { Column(Modifier.verticalScroll(rememberScrollState())) { Text(stringResource(R.string.delete_device_data_message)) } },
            confirmButton = {
                TextButton(
                    {
                        confirming = false
                        deleting = true
                        scope.launch {
                            try {
                                // 시작한 삭제는 화면을 다시 만들어도 끝까지 실행한다.
                                withContext(NonCancellable) { deleteLocalData() }
                                show(R.string.device_data_deleted)
                            } catch (error: CancellationException) {
                                throw error
                            } catch (_: Exception) {
                                show(R.string.deletion_failed)
                            } finally {
                                deleting = false
                            }
                        }
                    },
                    Modifier.heightIn(min = 48.dp),
                ) { Text(stringResource(R.string.delete)) }
            },
            dismissButton = { TextButton({ confirming = false }, Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

/** 기기 브라우저로 연다. 열 앱이 없어도 앱이 멈추지 않는다. */
@Composable
internal fun PrivacyPolicyLink(url: String) {
    val uriHandler = LocalUriHandler.current
    TextButton(
        { runCatching { uriHandler.openUri(url) } },
        Modifier.heightIn(min = 48.dp),
    ) { Text(stringResource(R.string.privacy_policy)) }
}

/** 지우거나 철회하는 버튼이다. [clickLabel]은 TalkBack이 누를 때 일어날 일로 읽는 동작 레이블이다(iOS 접근성 힌트). */
@Composable
internal fun DestructiveButton(
    @StringRes title: Int,
    enabled: Boolean = true,
    clickLabel: String? = null,
    onClick: () -> Unit,
) {
    OutlinedButton(
        onClick,
        Modifier.fillMaxWidth().heightIn(min = 48.dp)
            .then(if (clickLabel != null) Modifier.semantics { this.onClick(label = clickLabel, action = null) } else Modifier),
        enabled,
        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
    ) { Text(stringResource(title)) }
}
