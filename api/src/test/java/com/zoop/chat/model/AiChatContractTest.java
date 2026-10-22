package com.zoop.chat.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.chat.ChatStageReply;
import com.zoop.ai.http.HttpChatStageClient;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.model.CompanyNameResolver.Company;
import com.zoop.chat.model.CompanyNameResolver.Entry;
import com.zoop.chat.orchestrator.ChatBranchContext;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.orchestrator.ChatModels.Failure.Fate;
import com.zoop.chat.orchestrator.ChatQueryType;
import com.zoop.chat.orchestrator.ChatRouteDecision;
import com.zoop.chat.orchestrator.ChatSemanticVerdicts;
import com.zoop.chat.service.FrozenSelection;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolResult;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Real Java adapters -> ai/service (uvicorn) -> installed {@code zoop-ai-chat}, replay only. The inputs are built by the
 * production {@link ChatModelStages} from the same synthetic scenario the gate authored its replay fixture from
 * ({@code api/scripts/ai_chat_gate.py}); the replay answers only an input identical in every field, so a passing stage proves
 * the two sides agree on {@code zoop-ai-chat-1}. Not runnable on its own: {@code make api-ai-chat-smoke} starts the service and
 * exports {@code ZOOP_AI_CHAT_CONTRACT_MANIFEST}. Without it every test fails; none skips.
 */
@Tag("ai-chat-contract")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class AiChatContractTest {
    private static final String SOURCE = "src-chat-synthetic";
    private static final String EVIDENCE = "ev-" + "1".repeat(64);
    private static final String UNGRANTED_EVIDENCE = "ev-" + "2".repeat(64);
    private static final String QUOTE = "삼성전자가 HBM 공급 계약을 맺었다.";
    private static final String ROUTER_QUESTION = "PER이 뭐야? 삼성전자 관련 사건 알려줘";
    private static final String ANSWER_QUESTION = "삼성전자 관련 사건 알려줘";
    private static final String EVIDENCE_TEXT = "삼성전자는 HBM 공급 계약을 맺었습니다.";
    private static final String GENERAL_TEXT = "PER은 주가를 주당순이익으로 나눈 값입니다.";
    private static final Set<String> BOUND = Set.of("company.read", "issue.read");
    private static final List<Entry> CATALOG = List.of(new Entry("삼성전자", new Company("c-samsung", "삼성전자", "005930")));

    private final List<HttpChatStageClient> clients = new ArrayList<>();
    private final List<String> recorded = new ArrayList<>();
    private final List<ChatStageReply.Receipt> receipts = new ArrayList<>();
    private String baseUrl;
    private String chatToken;
    private String readerToken;

    @BeforeAll
    void load() throws IOException {
        String path = System.getenv("ZOOP_AI_CHAT_CONTRACT_MANIFEST");
        if (path == null || path.isBlank()) {
            fail("ZOOP_AI_CHAT_CONTRACT_MANIFEST is not set. These tests need a live ai/service: run `make api-ai-chat-smoke`.");
        }
        JsonNode manifest = JsonMapper.builder().build().readTree(Files.readString(Path.of(path)));
        baseUrl = manifest.get("baseUrl").stringValue();
        chatToken = manifest.get("chatToken").stringValue();
        readerToken = manifest.get("readerToken").stringValue();
    }

    @AfterAll
    void close() {
        clients.forEach(HttpChatStageClient::close);
    }

    private ChatModelStages stages(String token, String mode) {
        var client = new HttpChatStageClient(AiClientSettings.of(baseUrl, token, Duration.ofSeconds(3), Duration.ofSeconds(35),
                2_097_152));
        clients.add(client);
        return new ChatModelStages(client, mode, new CompanyNameResolver(null) {
            @Override
            public List<Mention> mentions(String text) {
                return match(text, CATALOG);
            }
        }, (evidenceId, graphVersion, asOf, traceId) -> Optional.ofNullable(Map.of(
                EVIDENCE, citation(EVIDENCE, "art-synthetic"),
                UNGRANTED_EVIDENCE, citation(UNGRANTED_EVIDENCE, "art-ungranted")).get(evidenceId)),
                articleId -> Optional.of(articleId.equals("art-synthetic") ? SOURCE : "src-chat-ungranted"),
                new ChatModelRecorder(null, Clock.systemUTC()) {
                    @Override
                    public String start(String jobId, String stage, String executionMode) {
                        return "aix-" + UUID.randomUUID();
                    }

                    @Override
                    public void finish(String id, String status, ChatStageReply.Receipt receipt, String errorCode) {
                        recorded.add(status + " " + errorCode);
                        receipts.add(receipt);
                    }
                });
    }

    private ChatModelStages stages() {
        return stages(chatToken, "replay");
    }

    private static Citation citation(String evidenceId, String articleId) {
        return new Citation("article", evidenceId, QUOTE, articleId, "v1", null, null, 0, QUOTE.length(), "합성 기사", "합성 언론사",
                Instant.parse("2026-10-20T00:00:00Z"), "https://example.test/synthetic");
    }

    /** A fresh job per call: each test's invocations are its own. */
    private static ChatRun run(String question) {
        String job = "chat-gate-" + UUID.randomUUID().toString().substring(0, 12);
        return new ChatRun(job, "chat-session-gate", "member-gate", 1, "run", List.of(new ChatRun.Turn(job, question, null, null)),
                new ChatFrozenContext(List.of(), 0, null, Instant.parse("2026-10-21T00:00:00Z"), "gv-synthetic"),
                FrozenSelection.NONE, "gv-synthetic", 0, Instant.parse("2026-10-22T00:00:00Z"),
                Instant.parse("2026-10-22T00:01:00Z"));
    }

    private static ChatBranchContext context(String evidenceId) {
        var result = new ChatToolResult("chat-tool-1", "tc-1", "company.read", "gv-synthetic",
                List.of(new ChatToolItem("c-samsung", "company", "삼성전자", List.of("c-samsung"), List.of(evidenceId))),
                List.of(evidenceId), false, false, null);
        var branch = new ChatBranchContext.Branch("r1", ANSWER_QUESTION, Set.of(ChatQueryType.Q03), false, List.of(result), false);
        return new ChatBranchContext(List.of(), null, List.of(branch), 20);
    }

    private static Fate fate(Runnable call) {
        return assertThrows(ChatModels.Failure.class, call::run).fate();
    }

    @Test
    void theRouterAnswersTheServerSplitRequirementsWithTypedProbabilities() {
        ChatRouteDecision decision = stages().route(run(ROUTER_QUESTION), BOUND);
        assertNull(decision.ambiguity());
        var concept = decision.requirements().get(0);
        var facts = decision.requirements().get(1);
        assertEquals("PER이 뭐야", concept.label());
        assertEquals(0.93, concept.types().get(ChatQueryType.Q02));
        assertEquals(0.88, facts.types().get(ChatQueryType.Q03));
        assertEquals(Map.of("company.read", 0.91, "issue.read", 0.84), facts.capabilities());
        assertEquals(List.of("c-samsung"), facts.targets());
        assertEquals(0.03, facts.prohibitedAdvice());
        assertEquals("succeeded null", recorded.getLast());
        assertEquals("authored-synthetic-chat-router", receipts.getLast().model());
        assertEquals("replay", receipts.getLast().executionMode());
    }

    @Test
    void theAnswerIsGeneratedFromTheGrantedQuote() {
        ChatGeneratedAnswer answer = stages().generate(run(ANSWER_QUESTION), context(EVIDENCE));
        assertEquals(List.of(new ChatGeneratedAnswer.Section("evidence_grounded", EVIDENCE_TEXT, List.of("r1"), List.of(EVIDENCE))),
                answer.sections());
        assertEquals(List.of("c-samsung"), answer.graphTargetIds());
        assertEquals("authored-synthetic-chat-answer", receipts.getLast().model());
    }

    @Test
    void theVerifierJudgesEachSection() {
        var sections = List.of(
                new ChatGeneratedAnswer.Section("evidence_grounded", EVIDENCE_TEXT, List.of("r1"), List.of(EVIDENCE)),
                new ChatGeneratedAnswer.Section("general_knowledge", GENERAL_TEXT, List.of("r2"), List.of()));
        ChatSemanticVerdicts verdicts = stages().verify(run(ANSWER_QUESTION), sections, List.of(citation(EVIDENCE, "art-synthetic")));
        assertEquals(List.of(new ChatSemanticVerdicts.Verdict("supported", "no"), new ChatSemanticVerdicts.Verdict(null, "no")),
                verdicts.sections());
    }

    @Test
    void theSameInvocationIsAnsweredFromTheLedgerAndNeverSentAgain() {
        ChatModelStages stages = stages();
        ChatRun run = run(ROUTER_QUESTION);
        ChatRouteDecision first = stages.route(run, BOUND);
        ChatStageReply.Receipt sent = receipts.getLast();
        ChatRouteDecision again = stages.route(run, BOUND);
        assertEquals(first, again);
        assertEquals(sent.sentAt(), receipts.getLast().sentAt(), "a resend returns the stored outcome");
    }

    @Test
    void aQuoteWithoutAChatGrantIsRefusedBeforeSending() {
        assertEquals(Fate.REFUSED, fate(() -> stages().generate(run(ANSWER_QUESTION), context(UNGRANTED_EVIDENCE))));
        assertEquals("failed source_grant_denied", recorded.getLast());
        assertNull(receipts.getLast());
    }

    @Test
    void anInputTheFixtureDoesNotKnowIsRefusedNotGuessed() {
        assertEquals(Fate.REFUSED, fate(() -> stages().route(run("등록되지 않은 질문"), BOUND)));
        assertEquals("failed replay_input_mismatch", recorded.getLast());
    }

    @Test
    void liveModeIsRefusedWhileTheServiceGateIsClosed() {
        assertEquals(Fate.REFUSED, fate(() -> stages(chatToken, "live").route(run(ROUTER_QUESTION), BOUND)));
        assertEquals("failed execution_unavailable", recorded.getLast());
    }

    @Test
    void aPrincipalWithoutChatInvokeIsRefused() {
        assertEquals(Fate.REFUSED, fate(() -> stages(readerToken, "replay").route(run(ROUTER_QUESTION), BOUND)));
        assertEquals("failed scope_denied", recorded.getLast());
    }
}
