package com.zoop.chat.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicInteger;
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
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatToolCallReservation;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.model.CompanyNameResolver.Company;
import com.zoop.chat.model.CompanyNameResolver.Entry;
import com.zoop.chat.orchestrator.ChatBranchContext;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.orchestrator.ChatModels.Failure.Fate;
import com.zoop.chat.orchestrator.ChatQueryType;
import com.zoop.chat.orchestrator.ChatRouteDecision;
import com.zoop.chat.orchestrator.ChatSemanticVerdicts;
import com.zoop.chat.orchestrator.OrchestratedChatEngine;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatTool;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolScope;
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
 * the two sides agree on {@code zoop-ai-chat-2}. Not runnable on its own: {@code make api-ai-chat-smoke} starts the service and
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
        }, new IssueNameResolver(null) {
            @Override
            public Names at(String graphVersion, java.time.Instant asOf) {
                return NONE;
            }
        }, (evidenceId, graphVersion, asOf, traceId) -> Optional.ofNullable(Map.of(
                EVIDENCE, citation(EVIDENCE, "art-synthetic"),
                UNGRANTED_EVIDENCE, citation(UNGRANTED_EVIDENCE, "art-ungranted")).get(evidenceId)),
                articleId -> Optional.of(articleId.equals("art-synthetic") ? SOURCE : "src-chat-ungranted"),
                new ChatModelRecorder(null, Clock.systemUTC()) {
                    @Override
                    public String start(String jobId, int attemptNo, String stage, String executionMode) {
                        return "aix-" + UUID.randomUUID();
                    }

                    @Override
                    public void finish(String id, String status, String sendState, ChatStageReply.Receipt receipt, String errorCode) {
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
        return run(question, "chat-gate-" + UUID.randomUUID().toString().substring(0, 12));
    }

    private static ChatRun run(String question, String job) {
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
        ChatRun run = run(ANSWER_QUESTION, "chat-verify-gate");
        ChatSemanticVerdicts verdicts = stages().verify(run, sections, List.of(citation(EVIDENCE, "art-synthetic")),
                ChatModels.ServerFacts.withoutTools(run, sections));
        assertEquals(List.of(new ChatSemanticVerdicts.Verdict("supported", "no"), new ChatSemanticVerdicts.Verdict(null, "no")),
                verdicts.sections());
    }

    @Test
    void theOrchestratorSendsBoundMemberAndComparisonFacts() {
        AtomicInteger reads = new AtomicInteger();
        var registry = new ChatToolRegistry(List.of(
                new ChatTool() {
                    public ChatCapability capability() { return ChatCapability.PORTFOLIO_SCOPE_READ; }
                    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest query) {
                        reads.incrementAndGet();
                        assertEquals("member-gate", scope.memberId());
                        return new ChatToolOutput("member-scope", List.of(
                                new ChatToolItem("KRX:005930", "company", "삼성전자 (보유)", List.of("KRX:005930"), List.of()),
                                new ChatToolItem("NASDAQ:NVDA", "company", "NVIDIA (관심)", List.of("NASDAQ:NVDA"), List.of())),
                                List.of(), true, false);
                    }
                },
                new ChatTool() {
                    public ChatCapability capability() { return ChatCapability.GRAPH_VERSION_DIFF; }
                    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest query) {
                        reads.incrementAndGet();
                        assertEquals(List.of("KRX:005930", "NASDAQ:NVDA"), query.targets());
                        return new ChatToolOutput("gv-earlier.." + scope.graphVersionId(), List.of(
                                new ChatToolItem("iss-new", "issue", "[새로 생김] 공급 계약", List.of("KRX:005930"), List.of(EVIDENCE)),
                                new ChatToolItem("iss-old", "issue", "[사라짐] 이전 사건", List.of("NASDAQ:NVDA"), List.of()),
                                new ChatToolItem("edge-stable", "edge",
                                        "[새로 생김] " + "가".repeat(298) + "\uD840\uDC00" + "끝".repeat(20),
                                        List.of("KRX:005930", "NASDAQ:NVDA"), List.of(EVIDENCE))),
                                List.of(EVIDENCE), true, false);
                    }
                }));
        ChatModels.Router router = (run, bound) -> new ChatRouteDecision(List.of(new ChatRouteDecision.Requirement(
                "r1", "내 종목 지도 변경", true, Map.of(ChatQueryType.Q05, 0.9, ChatQueryType.Q07, 0.9),
                Map.of("portfolio.scope.read", 0.9, "graph.version.diff", 0.9), List.of(), 0.0, null)), null);
        ChatModels.Generator generator = (run, context) -> {
            assertEquals(1, context.branches().size(), "scope branch is merged into its parent");
            return new ChatGeneratedAnswer(List.of(new ChatGeneratedAnswer.Section("evidence_grounded",
                    "보유 종목 삼성전자와 관심 종목 NVIDIA의 조회된 지도 변경입니다.", List.of("r1"), List.of(EVIDENCE))),
                    List.of(), List.of());
        };
        var control = new GateControl();
        try (var runner = new ChatToolRunner(registry);
                var engine = new OrchestratedChatEngine(router, generator, stages(), registry, runner,
                        (id, version, asOf, trace) -> Optional.of(citation(id, "art-synthetic")),
                        Clock.fixed(Instant.parse("2026-10-22T00:00:00Z"), ZoneOffset.UTC))) {
            var outcome = assertInstanceOf(ChatEngineOutcome.Completed.class,
                    engine.answer(run("내 종목 지도 변경", "chat-facts-gate"), control));
            assertEquals("answered", outcome.result().outcome());
        }
        assertEquals(2, reads.get(), "verifier must not requery membership");
        assertEquals(3, control.modelCalls);
        assertEquals("replay", receipts.getLast().executionMode());
    }

    private static final class GateControl implements ChatRunControl {
        int modelCalls;
        int toolCalls;
        public void phase(String phase) { }
        public void beforeModelCall() { modelCalls++; }
        public Duration remaining() { return Duration.ofSeconds(60); }
        public void shortenDeadline(Instant deadline) { }
        public boolean owned() { return true; }
        public int toolCallsLeft() { return 12; }
        public List<String> reserveToolCalls(int revision, List<ChatToolCallReservation> calls) {
            List<String> ids = new ArrayList<>();
            for (var ignored : calls) ids.add("tc-gate-" + toolCalls++);
            return ids;
        }
        public void toolCallStarted(String id) { }
        public Optional<String> claimToolCall(String capabilityId, String inputDigest) { return Optional.empty(); }
        public void toolCallFinished(String id, ChatToolCallEnd end) { }
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
        // The service knows a supported model, so the request reaches the live gate itself; enable, budget and keys are unset.
        assertEquals(Fate.REFUSED, fate(() -> stages(chatToken, "live").route(run(ROUTER_QUESTION), BOUND)));
        assertEquals("failed chat_live_disabled", recorded.getLast());
        assertNull(receipts.getLast(), "nothing was sent");
    }

    @Test
    void aPrincipalWithoutChatInvokeIsRefused() {
        assertEquals(Fate.REFUSED, fate(() -> stages(readerToken, "replay").route(run(ROUTER_QUESTION), BOUND)));
        assertEquals("failed scope_denied", recorded.getLast());
    }
}
