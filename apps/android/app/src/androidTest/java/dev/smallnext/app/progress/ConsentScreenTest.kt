package dev.smallnext.app.progress

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.UriHandler
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isFocused
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.data.AppDatabase
import dev.smallnext.app.progress.SuggestionCandidate.Action
import java.util.UUID
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * AI 전송 동의 화면·철회·기기 기록 전체 삭제(#359)의 TalkBack 의미와 상호작용을 확인한다.
 * iOS `AIConsentView`·`CoreFlowView`의 문구와 같다.
 */
@RunWith(AndroidJUnit4::class)
class ConsentScreenTest {
    @get:Rule
    val compose = createComposeRule()

    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val name = "smallnext-test-${UUID.randomUUID()}.sqlite"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val database by lazy { AppDatabase.open(context, name) }
    private val store = MemoryConsentStore()
    private val consent = AIConsent(store)
    private val openedLinks = mutableListOf<String>()
    private val privacy = "https://example.invalid/privacy"

    private val first = ProposedAction("주간 업무 보고서 문서에서 이번 주에 끝낸 업무 한 줄 적기", "업무 이름이 한 줄 남는다", 3)

    @After
    fun tearDown() {
        scope.cancel()
        database.close()
        context.deleteDatabase(name)
    }

    private fun emptyFlow() = runBlocking { ProgressFlow.open(database, UnavailableSuggestionProvider, scope) }

    /** 목표를 확인하고 첫 행동을 받은 흐름이다. */
    private fun flowWithGoal(): ProgressFlow {
        val flow = runBlocking { ProgressFlow.open(database, goalPreparing(ScriptedProvider(Action(first))), scope) }
        runBlocking {
            flow.prepareGoal(GoalInput("분기 업무 보고서 초안 쓰기"))
            flow.awaitSuggestion()
            flow.confirmGoal("분기 업무 보고서 초안 쓰기")
            flow.awaitSuggestion()
        }
        return flow
    }

    private fun show(flow: ProgressFlow, consent: AIConsent? = this.consent, url: String? = privacy, fontScale: Float? = null) = compose.setContent {
        val density = LocalDensity.current
        val links = object : UriHandler {
            override fun openUri(uri: String) {
                openedLinks.add(uri)
            }
        }
        CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale ?: density.fontScale), LocalUriHandler provides links) {
            CoreFlowApp(CompletableDeferred(flow), consent, url)
        }
    }

    private fun sql(statement: String) = database.openHelper.writableDatabase.execSQL(statement)

    private fun count(query: String) = database.openHelper.writableDatabase.query(query).use { it.moveToFirst(); it.getLong(0) }

    private fun waitForText(text: String) =
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text)).fetchSemanticsNodes().size == 1 }

    private fun waitUntilGone(text: String) =
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text)).fetchSemanticsNodes().isEmpty() }

    /** 알림이 닫힌 뒤 초점이 결과 문구로 옮겨지는 것을 기다린다. */
    private fun waitUntilFocused(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text) and isFocused()).fetchSemanticsNodes().size == 1 }
        compose.onNodeWithText(text).assertIsFocused()
    }

    private fun assertHeading(text: String) =
        compose.onNodeWithText(text).assert(SemanticsMatcher.keyIsDefined(SemanticsProperties.Heading))

    private fun SemanticsNodeInteraction.assertClickLabel(label: String) = assert(
        SemanticsMatcher("클릭 레이블 '$label'과 클릭 동작") {
            val click = it.config.getOrNull(SemanticsActions.OnClick)
            click?.label == label && click.action != null
        },
    )

    /** 스크롤하는 본문의 버튼을 누른다. 대화상자 버튼은 스크롤 영역이 없어 [tap]을 쓴다. */
    private fun click(text: String) = compose.onNodeWithText(text).performScrollTo().performSemanticsAction(SemanticsActions.OnClick)

    private fun tap(text: String) = compose.onNodeWithText(text).performSemanticsAction(SemanticsActions.OnClick)

    private fun assertFullyLaidOut(text: String) {
        val results = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText(text).performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(results) }
        val layout = results.single()
        val last = layout.lineCount - 1
        assertFalse(text, layout.didOverflowHeight || layout.isLineEllipsized(last))
        assertEquals(text, text.length, layout.getLineEnd(last))
        assertTrue(text, layout.size.width <= layout.layoutInput.constraints.maxWidth)
    }

    private val title = "AI 제안 전송 동의"
    private val sending = "작은 행동을 제안하려면 입력한 목표, 완료 조건, 자료 링크·발췌, 행동 기록과 답을 Smallnext 서버를 거쳐 Anthropic(Claude)으로 보냅니다."
    private val anonymous = "요청에는 익명 계정이 함께 쓰입니다. 이름이나 연락처는 묻지 않습니다."
    private val required = "모든 행동 제안에 AI를 쓰므로 동의해야 시작할 수 있습니다. 동의 전에는 AI로 아무것도 보내지 않습니다. 목표 목록에서 언제든 동의를 철회할 수 있습니다."
    private val agree = "동의하고 계속"
    private val deleteButton = "이 기기의 목표와 기록 삭제"
    private val deleted = "이 기기의 목표와 기록을 삭제했어요."
    private val failed = "삭제하지 못했어요. 다시 시도해 주세요."
    private val dialogTitle = "이 기기의 목표와 기록을 삭제할까요?"

    // 동의 전에는 동의 화면만 나온다. 문구는 iOS와 같고, 제목은 heading이다. 동의하고 계속은 48dp 이상이고 동작 레이블이 있다.
    @Test
    fun consentScreenShowsTheSameCopyAndAccessibleStructure() {
        show(emptyFlow())
        waitForText(title)
        assertHeading(title)
        for (text in listOf(sending, anonymous, required)) compose.onNodeWithText(text).assertExists()
        compose.onNodeWithText("목표 목록").assertDoesNotExist()
        compose.onNodeWithText(agree).assertHeightIsAtLeast(48.dp)
            .assertClickLabel("목표와 자료를 Anthropic으로 보내는 데 동의합니다.")
        compose.onNodeWithText("개인정보 처리방침").assertHeightIsAtLeast(48.dp)
        // 기록이 없으면 삭제 버튼을 보이지 않는다.
        compose.onNodeWithText(deleteButton).assertDoesNotExist()
    }

    // 처리방침은 기기 브라우저로 연다.
    @Test
    fun privacyPolicyLinkOpensTheAddress() {
        show(emptyFlow())
        waitForText(title)
        click("개인정보 처리방침")
        assertEquals(listOf(privacy), openedLinks)
    }

    @Test
    fun privacyPolicyLinkIsHiddenWithoutAnAddress() {
        show(emptyFlow(), url = null)
        waitForText(title)
        compose.onNodeWithText("개인정보 처리방침").assertDoesNotExist()
    }

    // 동의하면 핵심 흐름으로 간다. 동의는 앱 전용 저장소에 남는다.
    @Test
    fun agreeingStoresConsentAndOpensTheCoreFlow() {
        show(emptyFlow())
        waitForText(title)
        click(agree)
        waitUntilGone(title)
        compose.onNodeWithText("목표 목록").assertExists()
        assertTrue(store.value)
    }

    // 동의를 저장하지 못하면 동의 화면에 남고 저장 실패를 알린다.
    @Test
    fun consentStaysRequiredWhenStoringFails() {
        store.failing = true
        show(emptyFlow())
        waitForText(title)
        click(agree)
        waitForText("저장하지 못했어요. 다시 시도해 주세요.")
        compose.onNodeWithText(title).assertExists()
        assertFalse(store.value)
        store.failing = false
        click(agree)
        waitUntilGone(title)
    }

    // 동의를 이미 했다면 동의 화면 없이 핵심 흐름이 열린다. 플래그 OFF(consent 없음)도 같다.
    @Test
    fun grantedOrDisabledConsentOpensTheCoreFlowDirectly() {
        consent.grant()
        show(flowWithGoal())
        waitForText(first.task)
        compose.onNodeWithText(title).assertDoesNotExist()
    }

    @Test
    fun withoutConsentGateNothingChangesInTheGoalList() {
        // 플래그 OFF는 동의 게이트와 처리방침 주소를 모두 넘기지 않는다(MainActivity).
        show(flowWithGoal(), consent = null, url = null)
        waitForText(first.task)
        click("목표 목록")
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("새 목표")).fetchSemanticsNodes().size == 1 }
        compose.onNodeWithText("AI 전송 동의 철회").assertDoesNotExist()
        compose.onNodeWithText("개인정보 처리방침").assertDoesNotExist()
    }

    // 서버 AI가 켜져 있으면 목표 목록에도 처리방침 링크가 있고 기기 브라우저로 연다.
    @Test
    fun goalListShowsThePrivacyPolicyLinkWhenServerAIIsOn() {
        consent.grant()
        show(flowWithGoal())
        waitForText(first.task)
        click("목표 목록")
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("새 목표")).fetchSemanticsNodes().size == 1 }
        click("개인정보 처리방침")
        assertEquals(listOf(privacy), openedLinks)
    }

    // 목표 목록의 'AI 전송 동의 철회'는 동의 화면으로 돌아간다. 기록은 지우지 않는다. 동작 레이블은 iOS 힌트와 같은 뜻이다.
    @Test
    fun withdrawingFromTheGoalListReturnsToConsentAndKeepsRecords() {
        consent.grant()
        val flow = flowWithGoal()
        show(flow)
        waitForText(first.task)
        click("목표 목록")
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("새 목표")).fetchSemanticsNodes().size == 1 }
        compose.onNodeWithText("AI 전송 동의 철회").performScrollTo().assertHeightIsAtLeast(48.dp)
            .assertClickLabel("이후 목표와 자료를 AI로 보내지 않습니다. 동의 화면에서 기기의 기록을 삭제할 수 있습니다.")
        click("AI 전송 동의 철회")
        waitForText(title)
        assertFalse(store.value)
        assertFalse(consent.isGranted())
        // 기록이 있으면 동의 없이도 지울 수 있게 삭제 버튼이 보인다. 철회만으로는 지우지 않는다.
        compose.onNodeWithText(deleteButton).assertExists()
        assertEquals(1L, count("SELECT COUNT(*) FROM goal"))
        // 다시 동의하면 보존한 행동으로 돌아온다.
        click(agree)
        waitForText(first.task)
    }

    // 철회를 저장하지 못하면 동의를 그대로 두고 저장 실패를 알린다.
    @Test
    fun withdrawalStaysGrantedWhenStoringFails() {
        consent.grant()
        show(flowWithGoal())
        waitForText(first.task)
        click("목표 목록")
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("새 목표")).fetchSemanticsNodes().size == 1 }
        store.failing = true
        click("AI 전송 동의 철회")
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("저장하지 못했어요. 다시 시도해 주세요.")).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(title).assertDoesNotExist()
        assertTrue(consent.isGranted())
    }

    // 삭제는 확인 대화상자를 거친다. 취소하면 아무것도 지우지 않는다. 확인하면 모두 지우고 결과 문구가 초점을 받는다. 동의는 그대로다.
    @Test
    fun deletingAllRecordsAsksFirstAndMovesFocusToTheResult() {
        val flow = flowWithGoal()
        show(flow)
        waitForText(title)
        compose.onNodeWithText(deleteButton).performScrollTo().assertHeightIsAtLeast(48.dp)
        click(deleteButton)
        waitForText(dialogTitle)
        compose.onNodeWithText("삭제").assertHeightIsAtLeast(48.dp)
        compose.onNodeWithText("취소").assertHeightIsAtLeast(48.dp)
        compose.onNodeWithText("모든 목표의 행동·결과·입력·완료 기록과 작성 중인 목표를 지워요. 삭제 후에는 복구할 수 없어요.").assertExists()
        tap("취소")
        waitUntilGone(dialogTitle)
        assertEquals(1L, count("SELECT COUNT(*) FROM goal"))

        click(deleteButton)
        waitForText(dialogTitle)
        tap("삭제")
        waitForText(deleted)
        waitUntilFocused(deleted)
        assertEquals(0L, count("SELECT COUNT(*) FROM goal"))
        assertEquals(0L, count("SELECT COUNT(*) FROM action"))
        assertTrue(flow.state.value.goals.isEmpty())
        // 기록이 없으므로 삭제 버튼은 사라지고 동의 화면은 그대로다. 동의를 하지 않았다.
        compose.onNodeWithText(deleteButton).assertDoesNotExist()
        compose.onNodeWithText(title).assertExists()
        assertFalse(store.value)
    }

    // 작성 중인 새 목표 입력만 있어도 삭제할 수 있다.
    @Test
    fun unsubmittedGoalInputAlsoShowsDelete() {
        val flow = emptyFlow()
        runBlocking { flow.updateGoalInput(GoalInput(statement = "아직 제출하지 않은 목표")) }
        show(flow)
        waitForText(title)
        compose.onNodeWithText(deleteButton).assertExists()
        click(deleteButton)
        waitForText(dialogTitle)
        tap("삭제")
        waitForText(deleted)
        assertEquals(GoalInput(), flow.state.value.goalInput)
        assertEquals(0L, count("SELECT COUNT(*) FROM app_metadata WHERE `key` != 'schema_version'"))
    }

    // 삭제하지 못하면 아무것도 지우지 않고 다시 시도할 수 있다. 결과 문구가 초점을 받는다.
    @Test
    fun deletionFailureKeepsRecordsAndAllowsRetry() {
        val flow = flowWithGoal()
        sql("CREATE TRIGGER block_goal_delete BEFORE DELETE ON goal BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        show(flow)
        waitForText(title)
        click(deleteButton)
        waitForText(dialogTitle)
        tap("삭제")
        waitForText(failed)
        waitUntilFocused(failed)
        assertEquals(1L, count("SELECT COUNT(*) FROM goal"))
        compose.onNodeWithText(deleteButton).assertExists()
        sql("DROP TRIGGER block_goal_delete")
        click(deleteButton)
        waitForText(dialogTitle)
        tap("삭제")
        waitForText(deleted)
        waitUntilFocused(deleted)
        assertEquals(0L, count("SELECT COUNT(*) FROM goal"))
    }

    // 최대 글꼴에서도 문구가 잘리지 않고 버튼은 48dp 이상이다.
    @Test
    fun largestFontKeepsConsentCopyAndButtonsUsable() {
        show(flowWithGoal(), fontScale = 2f)
        waitForText(title)
        for (text in listOf(title, sending, anonymous, required)) {
            compose.onNodeWithText(text).performScrollTo()
            assertFullyLaidOut(text)
        }
        compose.onNodeWithText(agree).performScrollTo().assertHeightIsAtLeast(48.dp)
        compose.onNodeWithText(deleteButton).performScrollTo().assertHeightIsAtLeast(48.dp)
        compose.onNodeWithText("개인정보 처리방침").performScrollTo().assertHeightIsAtLeast(48.dp)
    }
}
