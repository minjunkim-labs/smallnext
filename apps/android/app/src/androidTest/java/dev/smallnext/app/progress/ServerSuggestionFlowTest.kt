package dev.smallnext.app.progress

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.smallnext.app.data.AppDatabase
import java.net.SocketException
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** [ServerSuggestionProvider]를 진행 흐름에 넣어 가짜 전송으로 첫 행동을 받고, 전송 실패 뒤에도 진행이 남는지 확인한다. */
@RunWith(AndroidJUnit4::class)
class ServerSuggestionFlowTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val name = "smallnext-test-${UUID.randomUUID()}.sqlite"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val databases = mutableListOf<AppDatabase>()
    private val calls = AtomicInteger()

    @After
    fun tearDown() {
        scope.cancel()
        databases.forEach { it.close() }
        context.deleteDatabase(name)
    }

    /** 첫 호출은 행동을 받고, 이후 호출은 연결이 끊긴다. */
    private val transport = Interceptor { chain ->
        if (calls.incrementAndGet() > 1) throw SocketException("Connection reset")
        val body = Buffer().also { chain.request().body?.writeTo(it) }.readUtf8()
        val input = JsonParser.parseString(body).asJsonObject["input"].asJsonObject
        val proposal = JsonObject().apply {
            addProperty("status", "action")
            addProperty("action", "관련 메모 하나 열기")
            addProperty("completion_condition", "메모가 화면에 열려 있다")
            addProperty("estimated_minutes", 2.5)
            addProperty("reason", "바로 시작할 수 있다")
            add("remaining_work", input["remaining_work"])
            add("preserved_completed_ids", input["completed_ids"])
            addProperty("goal_completed", false)
            addProperty("current_action_completed", false)
        }
        val data = JsonObject().apply { addProperty("disposition", "accepted"); add("proposal", proposal) }.toString()
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK").body(data.toResponseBody()).build()
    }

    private suspend fun makeFlow(transport: Interceptor = this.transport) = ProgressFlow.open(
        AppDatabase.open(context, name).also(databases::add),
        goalPreparing(
            ServerSuggestionProvider.create("https://api.example.invalid", { "test-token" }, OkHttpClient.Builder().addInterceptor(transport).build()),
        ),
        scope,
    )

    @Test
    fun testServerProviderGivesFirstActionAndTransportFailureKeepsProgressWithoutRetry() = runBlocking {
        val flow = makeFlow()
        flow.prepareGoal(GoalInput("주간 보고서 쓰기"))
        flow.awaitSuggestion()
        flow.confirmGoal("주간 보고서 쓰기")
        flow.awaitSuggestion()
        val card = (flow.state.value.screen as ProgressScreen.CurrentAction).card
        assertEquals(ActionCard(card.id, "관련 메모 하나 열기", "메모가 화면에 열려 있다", 3), card)

        flow.complete(card.id)
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.AwaitingNextAction(SuggestionProblem.Failure(SuggestionFailure.CONNECTION_LOST)), flow.state.value.screen)
        delay(200)
        assertEquals(2, calls.get())

        databases.forEach { it.close() }
        databases.clear()
        val reopened = makeFlow()
        assertEquals(ProgressScreen.AwaitingNextAction(SuggestionProblem.Failure(SuggestionFailure.CONNECTION_LOST)), reopened.state.value.screen)
        assertEquals("주간 보고서 쓰기", reopened.state.value.goal?.statement)
        val completions = databases.single().openHelper.readableDatabase.query("SELECT COUNT(*) FROM completion").use { it.moveToFirst(); it.getLong(0) }
        assertEquals(1L, completions)
        assertEquals(2, calls.get())
    }

    // 정보 부족 안내와 행동 확인 질문(#356)의 서버 경로. 이름은 iOS `ProgressFlowTests`와 같다. Android에는 개발 경로 어댑터가 없어 서버 경로만 확인한다.

    private val first = ProposedAction("관련 메모 하나 열기", "메모가 화면에 열려 있다", 3)
    private val actionKinds = listOf(SuggestionKind.FIRST_ACTION, SuggestionKind.SMALLER, SuggestionKind.NEXT_ACTION, SuggestionKind.REPLACEMENT)

    private val probe get() = databases.first().openHelper.writableDatabase

    private fun count(sql: String) = probe.query(sql).use { it.moveToFirst(); it.getLong(0) }

    /** 요청 경로와 `input`을 [requests]에 남기고, [respond]가 만든 `proposal`을 `accepted` 응답으로 돌려준다. */
    private fun recording(requests: MutableList<Pair<String, JsonObject>>, respond: (JsonObject) -> JsonObject) = Interceptor { chain ->
        val body = Buffer().also { chain.request().body?.writeTo(it) }.readUtf8()
        val input = JsonParser.parseString(body).asJsonObject["input"].asJsonObject
        requests.add(chain.request().url.encodedPath to input)
        val data = JsonObject().apply { addProperty("disposition", "accepted"); add("proposal", respond(input)) }.toString()
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK").body(data.toResponseBody()).build()
    }

    private fun proposal(input: JsonObject, status: String, action: String, completion: String, minutes: Double, reason: String) = JsonObject().apply {
        addProperty("status", status)
        addProperty("action", action)
        addProperty("completion_condition", completion)
        addProperty("estimated_minutes", minutes)
        addProperty("reason", reason)
        add("remaining_work", input["remaining_work"])
        add("preserved_completed_ids", input["completed_ids"])
        addProperty("goal_completed", false)
        addProperty("current_action_completed", false)
    }

    private fun insufficient(input: JsonObject) = proposal(input, "insufficient_info", "", "", 0.0, InsufficientInfoFixture.REASON)

    private suspend fun startGoal(flow: ProgressFlow, statement: String) {
        flow.prepareGoal(GoalInput(statement))
        flow.awaitSuggestion()
        flow.confirmGoal(statement)
    }

    @Test
    fun testSharedHTTPNoticeAndMetadataStayIsolatedAndDeleteAtomically() = runBlocking {
        val requests = CopyOnWriteArrayList<Pair<String, JsonObject>>()
        val transport = recording(requests, ::insufficient)
        val flow = makeFlow(transport)
        startGoal(flow, "과거 경력 사실 정리")
        flow.awaitSuggestion()
        val originalScreen = flow.state.value.screen
        val shown = originalScreen as? ProgressScreen.InsufficientInfo ?: throw AssertionError("$originalScreen")
        assertFalse(shown.isPrevious)
        val notice = shown.notice
        val originalId = flow.state.value.goal!!.id
        assertEquals(InsufficientInfoFixture.REASON, notice.reason)
        assertEquals(SuggestionKind.FIRST_ACTION, notice.requestKind)
        assertEquals(1L, count("SELECT COUNT(*) FROM goal WHERE id = $originalId AND revision = ${notice.goalRevision}"))
        assertEquals(64, notice.inputFingerprint.length)
        assertTrue(kotlin.math.abs(System.currentTimeMillis() - notice.receivedAt) < 10_000)
        flow.startNewGoal()
        startGoal(flow, "과거 경력 사실 정리")
        flow.awaitSuggestion()
        val otherId = flow.state.value.goal!!.id
        val otherScreen = flow.state.value.screen
        flow.selectGoal(originalId)
        assertEquals(originalScreen, flow.state.value.screen)
        // 안내를 받은 뒤 목표 문구가 바뀌면 이전 입력에 대한 안내다. 문구를 되돌리면 지금 입력에 대한 안내로 돌아온다.
        flow.editGoalStatement("달라진 문구")
        val previous = flow.state.value.screen as? ProgressScreen.InsufficientInfo ?: throw AssertionError("${flow.state.value.screen}")
        assertTrue(previous.isPrevious)
        assertEquals(notice, previous.notice)
        assertEquals(flow.state.value.screen, makeFlow(transport).state.value.screen)
        flow.editGoalStatement("과거 경력 사실 정리")
        assertEquals(originalScreen, flow.state.value.screen)

        // 안내 메타데이터를 지우지 못하면 목표 삭제 전체를 되돌린다.
        probe.execSQL(
            "CREATE TRIGGER reject_notice_delete BEFORE DELETE ON app_metadata WHEN OLD.`key` = 'supplemental_context:$originalId' " +
                "BEGIN SELECT RAISE(ABORT, 'test failure'); END",
        )
        assertTrue(runCatching { flow.deleteGoal(originalId, confirmed = true) }.isFailure)
        assertEquals(2, flow.state.value.goals.size)
        assertEquals(originalScreen, flow.state.value.screen)
        assertEquals(originalScreen, makeFlow(transport).state.value.screen)
        probe.execSQL("DROP TRIGGER reject_notice_delete")
        flow.deleteGoal(originalId, confirmed = true)
        assertEquals(ProgressScreen.GoalInput, flow.state.value.screen)
        assertEquals(0L, count("SELECT COUNT(*) FROM app_metadata WHERE `key` = 'supplemental_context:$originalId'"))
        flow.selectGoal(otherId)
        assertEquals(otherScreen, flow.state.value.screen)
        val reopened = makeFlow(transport)
        assertEquals(otherScreen, reopened.state.value.screen)
        assertEquals(listOf(otherId), reopened.state.value.goals.map { it.id })
        assertEquals(2, requests.size)
        assertEquals(0L, count("SELECT COUNT(*) FROM action"))
        assertEquals(0L, count("SELECT COUNT(*) FROM completion"))
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE kind = 'first_action' AND status = 'applied'"))
    }

    @Test
    fun testHTTPQuestionsSendConfirmedAnswersWithOriginalScopeOnBothAdapters() = runBlocking {
        val question = InsufficientInfoFixture.QUESTION
        val answer = InsufficientInfoFixture.ANSWER
        for (kind in actionKinds) {
            databases.forEach { it.close() }
            databases.clear()
            context.deleteDatabase(name)
            val requests = CopyOnWriteArrayList<Pair<String, JsonObject>>()
            val flow = makeFlow(
                recording(requests) { input ->
                    val answered = input["available"].asJsonArray.any { it.asString == "행동 요청에서 이미 답한 질문: $question / 답: $answer" }
                    val requested = input["request_kind"].asString == kind.raw
                    when {
                        requested && answered -> insufficient(input)
                        requested -> proposal(input, "need_info", question, "알고 있는 답을 전한다", 0.0, "질문이 필요해요")
                        else -> proposal(input, "action", first.task, first.doneWhen, 3.0, "바로 시작할 수 있다")
                    }
                },
            )
            startGoal(flow, "과거 경력 사실 정리")
            if (kind != SuggestionKind.FIRST_ACTION) {
                flow.awaitSuggestion()
                val card = (flow.state.value.screen as ProgressScreen.CurrentAction).card
                when (kind) {
                    SuggestionKind.SMALLER -> flow.makeSmaller()
                    SuggestionKind.NEXT_ACTION -> flow.complete(card.id)
                    else -> flow.deferAction()
                }
            }
            flow.awaitSuggestion()
            val draft = flow.state.value.suggestionInput ?: throw AssertionError("$kind: ${flow.state.value.screen}")
            flow.updateSuggestionInput(answer, draft.requestId)
            assertEquals("$kind", if (kind == SuggestionKind.FIRST_ACTION) 1 else 2, requests.size)
            flow.answerQuestion(answer)
            flow.answerQuestion(answer)
            flow.awaitSuggestion()
            val screen = flow.state.value.screen as? ProgressScreen.InsufficientInfo ?: throw AssertionError("$kind: ${flow.state.value.screen}")
            assertEquals(kind, screen.notice.requestKind)
            assertFalse("$kind", screen.isPrevious)
            assertEquals("$kind", if (kind == SuggestionKind.FIRST_ACTION) 2 else 3, requests.size)
            val (path, input) = requests.last()
            assertEquals("/v1/suggestions", path)
            assertEquals(kind.raw, input["request_kind"].asString)
            assertEquals(if (kind == SuggestionKind.SMALLER) answer else "", input["current_blocker"].asString)
            assertEquals(if (kind == SuggestionKind.NEXT_ACTION) 1 else 0, input["completed_ids"].asJsonArray.size())
            val remaining = listOf("과거 경력 사실 정리") + if (kind == SuggestionKind.NEXT_ACTION || kind == SuggestionKind.FIRST_ACTION) emptyList() else listOf(first.task)
            assertEquals("$kind", remaining, input["remaining_work"].asJsonArray.map { it.asString })
        }
    }
}
