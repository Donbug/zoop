package com.zoop.chat.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalInt;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Function;

import com.zoop.ai.AiOperation;
import com.zoop.ai.AiServiceErrorException;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.chat.ChatStageCall;
import com.zoop.ai.chat.ChatStageReply;
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
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

/** The model port adapters over a scripted chat stage client: what is sent, how answers and failures are read. No model runs. */
class ChatModelStagesTest {
    private static final String JOB = "chat-job-0001";
    private static final String EV_A = "ev-" + "a".repeat(64);
    private static final String EV_B = "ev-" + "b".repeat(64);
    private static final Company HANMI_PHARM = new Company("c-hanmi-pharm", "한미약품", "128940");
    private static final Company HANMI_SCIENCE = new Company("c-hanmi-science", "한미사이언스", "008930");
    private static final Company SAMSUNG = new Company("c-samsung", "삼성전자", "005930");
    private static final List<Entry> CATALOG = List.of(new Entry("삼성전자", SAMSUNG), new Entry("한미약품", HANMI_PHARM), new Entry("한미사이언스", HANMI_SCIENCE),
            new Entry("한미", HANMI_PHARM),
            new Entry("한미", HANMI_SCIENCE));
    private static final ChatStageReply.Receipt RECEIPT = new ChatStageReply.Receipt("typesafe", "systemone-v1", "jev",
            "chat-router-1", "replay", 10L, 4L, null, Instant.parse("2026-10-22T01:00:00Z"), Instant.parse("2026-10-22T01:00:01Z"));

    private final List<ChatStageCall> calls = new ArrayList<>();
    private List<IssueNameResolver.Entry> issueCatalog = List.of();
    private boolean issueOutage;
    private int issueReads;
    private final List<String> recorded = new ArrayList<>();
    private Function<ChatStageCall, ChatStageReply> answer = call -> { throw new AssertionError("no call expected"); };

    private final ChatModelStages stages = stages(new ChatModelRecorder(null, Clock.systemUTC()) {
        @Override
        public String start(String jobId, int attemptNo, String stage, String mode) {
            recorded.add("start " + jobId + " " + attemptNo + " " + stage + " " + mode);
            return "aix-1";
        }

        @Override
        public void finish(String id, String status, String sendState, ChatStageReply.Receipt receipt, String errorCode) {
            recorded.add("finish " + status + " " + sendState + " " + (receipt == null ? "-" : receipt.model()) + " " + errorCode);
        }
    });

    private ChatModelStages stages(ChatModelRecorder recorder) {
        return new ChatModelStages(call -> {
            calls.add(call);
            return answer.apply(call);
        }, "replay", new CompanyNameResolver(null) {
        @Override
        public List<Mention> mentions(String text) {
            return match(text, CATALOG);
        }
    }, new IssueNameResolver(null) {
        @Override
        public Names at(String graphVersion, Instant asOf) {
            issueReads++;
            if (issueOutage) throw new com.zoop.chat.tool.ChatToolUnavailable("graph down");
            return text -> match(text, issueCatalog);
        }
    }, (evidenceId, graphVersion, asOf, traceId) -> evidenceId.equals(EV_A)
            ? Optional.of(citation(EV_A, "삼성전자가 HBM을 공급한다."))
            : Optional.empty(),
            articleId -> Optional.of("news-provider-1"), recorder);
    }

    private static Citation citation(String id, String quote) {
        return new Citation("article", id, quote, "art-1", "v1", null, null, 0, quote.length(), "기사 제목", "언론사",
                Instant.parse("2026-10-20T00:00:00Z"), "https://example.test/a");
    }

    private static ChatRun run(ChatRun.Turn... turns) {
        return new ChatRun(JOB, "chat-session-1", "member-1", 1, "run", List.of(turns),
                new ChatFrozenContext(List.of(), 0, null, Instant.parse("2026-10-21T00:00:00Z"), "gv-1"), FrozenSelection.NONE,
                "gv-1", 0, Instant.parse("2026-10-22T00:00:00Z"), Instant.parse("2026-10-22T00:01:00Z"));
    }

    private static ChatRun.Turn root(String question) {
        return new ChatRun.Turn(JOB, question, null, null);
    }

    private static ChatStageReply succeeded(ChatStageCall call, String answerJson) {
        return new ChatStageReply(call.invocationId(), call.stage(), true, StrictJson.parseObject(answerJson).node(), null,
                RECEIPT);
    }

    private static ChatStageReply failed(ChatStageCall call, boolean sent, boolean unknown) {
        return new ChatStageReply(call.invocationId(), call.stage(), false, null,
                new ChatStageReply.Failure("some_failure", sent, unknown), sent ? RECEIPT : null);
    }

    @Test
    void anAgentStepSendsTheGrantAndToolsButNoServerUrlAndReadsBothOutcomes() {
        var requirement = new com.zoop.chat.orchestrator.ChatModels.AgentRequirement("r1", "SK하이닉스 최근 사건", false,
                List.of("KRX:000660"), true);
        answer = call -> succeeded(call, """
                {"responseId":"resp_1","status":"approval_required","mcpCalls":[],"answer":null,
                 "approvalRequests":[{"approvalRequestId":"mcpr_1","toolName":"company_read","arguments":{"targets":["KRX:000660"],"limit":null},"requirementIds":["r1"]}]}""");
        var held = stages.step(run(root("SK하이닉스 최근 사건")), 1, new com.zoop.chat.orchestrator.ChatModels.AgentInput(
                List.of(requirement), "zmcp1.k1.payload.mac-synthetic", List.of("company_read"), "authored-replay", 20, null,
                List.of()));
        assertFalse(held.completed());
        assertEquals("company_read", held.approvals().getFirst().toolName());
        assertEquals(List.of("r1"), held.approvals().getFirst().requirementIds());
        assertTrue(held.approvals().getFirst().arguments().containsKey("limit"), "an explicit null is kept for the server check");

        var first = calls.getFirst();
        assertEquals("chat-agent", first.stage());
        assertEquals(JOB + ".1.agent-1", first.invocationId());
        var mcp = first.input().path("mcp");
        assertEquals("zmcp1.k1.payload.mac-synthetic", mcp.path("authorization").asString());
        assertFalse(mcp.has("serverUrl"), "the MCP server URL is the AI runtime operator's, never sent from here");
        assertEquals("authored-replay", mcp.path("recipient").asString(), "the recipient the results are checked for");
        assertEquals("KRX:000660", first.input().path("requirements").get(0).path("targets").get(0).asString());
        assertFalse(first.input().has("continuation"));

        answer = call -> succeeded(call, """
                {"responseId":"resp_2","status":"completed","approvalRequests":[],"mcpCalls":[{"toolName":"company_read","failed":false}],
                 "answer":{"sections":[{"basis":"evidence_grounded","text":"공급 계약","requirementIds":["r1"],"evidenceIds":["%s"]}],
                           "insufficientRequirementIds":[],"graphTargetIds":["KRX:000660"]}}""".formatted(EV_A));
        var done = stages.step(run(root("SK하이닉스 최근 사건")), 2, new com.zoop.chat.orchestrator.ChatModels.AgentInput(
                List.of(requirement), "zmcp1.k1.payload.mac-synthetic", List.of("company_read"), "authored-replay", 20, "resp_1",
                List.of(new com.zoop.chat.orchestrator.ChatModels.Decision("mcpr_1", true))));
        assertTrue(done.completed());
        assertEquals(List.of(EV_A), done.answer().sections().getFirst().evidenceIds());
        var continuation = calls.get(1).input().path("continuation");
        assertEquals("resp_1", continuation.path("previousResponseId").asString());
        assertTrue(continuation.path("decisions").get(0).path("approve").asBoolean());
    }

    @Test
    void theRouterGetsTheSplitRequirementsAndBoundCapabilitiesAndNamesAreResolvedByTheServer() {
        answer = call -> succeeded(call, """
                {"requirements":[
                  {"requirementId":"r1","types":{"Q02":0.9},"capabilities":{},"prohibitedAdvice":0.0,"dependsOn":null},
                  {"requirementId":"r2","types":{"Q03":0.8},"capabilities":{"company.read":0.9,"graph.version.diff":0.8},
                   "prohibitedAdvice":0.05,"dependsOn":null}]}""");
        ChatRouteDecision decision = stages.route(run(root("PER이 뭐야? 삼성전자 관련 사건 알려줘")), Set.of("company.read", "issue.read"));

        ChatStageCall call = calls.getFirst();
        assertEquals("chat-router", call.stage());
        assertEquals(JOB + ".1.router", call.invocationId());
        JsonNode input = call.input();
        assertEquals("PER이 뭐야? 삼성전자 관련 사건 알려줘", input.get("turns").get(0).get("text").stringValue());
        assertEquals("삼성전자 관련 사건 알려줘", input.get("requirements").get(1).get("text").stringValue());
        assertEquals(2, input.get("capabilities").size());
        assertTrue(input.toString().indexOf(SAMSUNG.id()) < 0, "company ids are never sent to the router");

        var r2 = decision.requirements().get(1);
        assertEquals(Map.of(ChatQueryType.Q03, 0.8), r2.types());
        assertEquals(Map.of("company.read", 0.9), r2.capabilities());
        assertEquals(List.of(SAMSUNG.id()), r2.targets());
        assertTrue(r2.explicit());
        assertEquals(List.of("start chat-job-0001 1 chat-router replay", "finish succeeded sent jev null"), recorded);
    }

    @Test
    void theRouterMapsAValidatedWireDependencyToTheServerCheckpoint() {
        answer = call -> succeeded(call, """
                {"requirements":[
                  {"requirementId":"r1","types":{"Q07":0.9,"Q04":0.9},
                   "capabilities":{"portfolio.scope.read":0.9,"graph.path.read":0.9},
                   "prohibitedAdvice":0.0,"dependsOn":null},
                  {"requirementId":"r2","types":{"Q03":0.9},"capabilities":{"company.read":0.9},
                   "prohibitedAdvice":0.0,
                   "dependsOn":{"requirementId":"r1","cardinality":"exactly","count":2}}]}""");

        ChatRouteDecision decision = stages.route(
                run(root("내 종목과 연결된 회사를 찾아줘? 정확히 두 곳이면 그 회사 최근 사건을 알려줘")),
                Set.of("portfolio.scope.read", "graph.path.read", "company.read"));

        assertNull(decision.requirements().getFirst().dependsOn());
        assertEquals(new ChatRouteDecision.Dependency("r1", "exactly", 2), decision.requirements().get(1).dependsOn());
    }

    @Test
    void aRequirementThatNamesItsCompanyReadsItInsteadOfDepending() {
        answer = call -> succeeded(call, """
                {"requirements":[
                  {"requirementId":"r1","types":{"Q07":0.9},"capabilities":{"portfolio.scope.read":0.9},
                   "prohibitedAdvice":0.0,"dependsOn":null},
                  {"requirementId":"r2","types":{"Q03":0.9},"capabilities":{"company.read":0.9},
                   "prohibitedAdvice":0.0,
                   "dependsOn":{"requirementId":"r1","cardinality":"atLeast","count":1}}]}""");

        ChatRouteDecision decision = stages.route(run(root("내 종목 찾아줘? 삼성전자 소식도 알려줘")),
                Set.of("portfolio.scope.read", "company.read"));

        assertEquals(List.of(SAMSUNG.id()), decision.requirements().get(1).targets());
        assertNull(decision.requirements().get(1).dependsOn());
    }

    @Test
    void aSharedNameIsAClarificationWithoutAnyModelCallUntilTheMemberPicks() {
        ChatRouteDecision decision = stages.route(run(root("한미 관련 공시 알려줘")), Set.of("company.read"));
        assertTrue(calls.isEmpty());
        assertEquals("company", decision.ambiguity().kind());
        assertEquals(List.of("c-hanmi-pharm", "c-hanmi-science"),
                decision.ambiguity().options().stream().map(ChatRouteDecision.Option::id).toList());

        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q03":0.9},"capabilities":{"company.read":0.9},
                  "prohibitedAdvice":0.0,"dependsOn":null}]}""");
        ChatRouteDecision picked = stages.route(run(root("한미 관련 공시 알려줘"),
                new ChatRun.Turn("chat-job-0002", "한미사이언스", "c-hanmi-science", "한미사이언스 (008930)")), Set.of("company.read"));
        assertNull(picked.ambiguity());
        assertEquals(List.of("c-hanmi-science"), picked.requirements().getFirst().targets());
        assertEquals("한미사이언스 (008930)", calls.getFirst().input().get("turns").get(1).get("choiceLabel").stringValue());
    }

    @Test
    void issuesNamedInTheQuestionAreTargetsAfterItsCompaniesAndSharedWordsAskWhichOne() {
        var supply = new IssueNameResolver.Entry("iss-supply", "차세대 HBM 공급 계약", "HBM", "공급 계약", "2026-09-22");
        var again = new IssueNameResolver.Entry("iss-supply-2", "HBM 추가 공급 계약", "HBM", "공급 계약", "2026-10-02");
        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q03":0.9},"capabilities":{},"prohibitedAdvice":0.0,"dependsOn":null}]}""");
        issueCatalog = List.of(supply);
        ChatRouteDecision named = stages.route(run(root("HBM 공급 계약에 삼성전자가 엮였어")), Set.of("issue.read"));
        assertEquals(List.of(SAMSUNG.id(), "iss-supply"), named.requirements().getFirst().targets());
        assertTrue(calls.getFirst().input().toString().indexOf("iss-supply") < 0, "issue ids are never sent to the router");

        calls.clear();
        issueCatalog = List.of(supply, again);
        ChatRouteDecision shared = stages.route(run(root("HBM 공급 계약 사건 알려줘")), Set.of("issue.read"));
        assertEquals(1, calls.size(), "issues are resolved after the router, so a shared issue name asks after it");
        assertEquals("other", shared.ambiguity().kind(), "the public choice kinds have none for issues");
        assertEquals(List.of("차세대 HBM 공급 계약 (2026-09-22)", "HBM 추가 공급 계약 (2026-10-02)"),
                shared.ambiguity().options().stream().map(ChatRouteDecision.Option::label).toList());

        ChatRouteDecision picked = stages.route(run(root("HBM 공급 계약 사건 알려줘"),
                new ChatRun.Turn("chat-job-0002", "HBM 추가 공급 계약", "iss-supply-2", "HBM 추가 공급 계약 (2026-10-02)")),
                Set.of("issue.read"));
        assertNull(picked.ambiguity());
        assertEquals(List.of("iss-supply-2"), picked.requirements().getFirst().targets());
    }

    @Test
    void aConceptQuestionNeverReadsTheGraphSoItIsRoutedWhileTheGraphIsDown() {
        issueCatalog = List.of(new IssueNameResolver.Entry("iss-supply", "차세대 HBM 공급 계약", "HBM", "공급 계약", null));
        issueOutage = true;
        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q02":0.9,"Q03":0.2},"capabilities":{},
                  "prohibitedAdvice":0.0,"dependsOn":null}]}""");
        ChatRouteDecision concept = stages.route(run(root("HBM 공급 계약이 뭐야")), Set.of("issue.read"));
        assertEquals(List.of(), concept.requirements().getFirst().targets(), "a concept names no issue");
        assertEquals(0, issueReads);

        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q02":0.6,"Q03":0.4},"capabilities":{},
                  "prohibitedAdvice":0.0,"dependsOn":null}]}""");
        assertThrows(com.zoop.chat.tool.ChatToolUnavailable.class,
                () -> stages.route(run(root("HBM 공급 계약이 뭐야")), Set.of("issue.read")),
                "a question that may look the issue up needs the graph, and its outage is the reads' outage");
        assertEquals(1, issueReads);
    }

    @Test
    void aZoopDocumentQuestionNeverReadsTheGraphSoItIsRoutedWhileThePinnedGraphIsDown() {
        // run() pins an active version, as the context freezer does without a selection; Q01 needs only ZOOP's documents.
        issueCatalog = List.of(new IssueNameResolver.Entry("iss-supply", "차세대 HBM 공급 계약", "HBM", "공급 계약", null));
        issueOutage = true;
        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q01":0.9},"capabilities":{"zoopPolicy.read":0.9},
                  "prohibitedAdvice":0.0,"dependsOn":null}]}""");
        ChatRouteDecision policy = stages.route(run(root("탈퇴하면 HBM 공급 계약 대화 기록은 어떻게 돼?")),
                Set.of("zoopPolicy.read", "issue.read"));
        assertEquals(1, policy.requirements().size());
        assertEquals(List.of(), policy.requirements().getFirst().targets());
        assertEquals(0, issueReads, "a document question is not held up by the graph");

        // A graph type none of whose capabilities is bound reads no graph either.
        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q01":0.9,"Q06":0.9},"capabilities":{"zoopPolicy.read":0.9},
                  "prohibitedAdvice":0.0,"dependsOn":null}]}""");
        stages.route(run(root("HBM 공급 계약 브리핑과 약관")), Set.of("zoopPolicy.read", "issue.read"));
        assertEquals(0, issueReads);
    }

    @Test
    void aCompanyNamedInAFreeTextReplyResolvesTheSharedNameOfTheQuestion() {
        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q03":0.9},"capabilities":{"company.read":0.9},
                  "prohibitedAdvice":0.0,"dependsOn":null}]}""");
        ChatRouteDecision typed = stages.route(run(root("한미 관련 공시 알려줘"),
                new ChatRun.Turn("chat-job-0002", "한미사이언스", null, null)), Set.of("company.read"));
        assertNull(typed.ambiguity());
        assertEquals(List.of("c-hanmi-science"), typed.requirements().getFirst().targets());
    }

    @Test
    void aFreeTextReplyNarrowsARootWithTooManyRequirements() {
        String seven = "A가 뭐야? B는? C는? D는? E는? F는? 삼성전자 관련 사건은?";
        ChatRouteDecision tooMany = stages.route(run(root(seven)), Set.of("company.read"));
        assertEquals(7, tooMany.requirements().size());
        assertTrue(calls.isEmpty(), "the router is not asked about more requirements than the planner accepts");

        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q02":0.9},"capabilities":{},"prohibitedAdvice":0.0,"dependsOn":null},
                  {"requirementId":"r2","types":{"Q03":0.9},"capabilities":{"company.read":0.9},"prohibitedAdvice":0.0,"dependsOn":null}]}""");
        ChatRouteDecision narrowed = stages.route(run(root(seven),
                new ChatRun.Turn("chat-job-0002", "A가 뭐야? 삼성전자 관련 사건은?", null, null)), Set.of("company.read"));
        assertEquals(List.of("A가 뭐야", "삼성전자 관련 사건은"),
                narrowed.requirements().stream().map(ChatRouteDecision.Requirement::label).toList());
        assertEquals(List.of("c-samsung"), narrowed.requirements().get(1).targets());
        assertEquals(seven, calls.getFirst().input().get("turns").get(0).get("text").stringValue(), "the whole chain is sent");
    }

    @Test
    void theGeneratorGetsQuotesWithTheirSourceAndOnlyReadableEvidence() {
        answer = call -> succeeded(call, """
                {"sections":[{"basis":"evidence_grounded","text":"공급합니다.","requirementIds":["r1"],"evidenceIds":["%s"]}],
                 "insufficientRequirementIds":[],"graphTargetIds":["c-samsung"]}""".formatted(EV_A));
        var result = new ChatToolResult("chat-tool-1", "tc-1", "company.read", "gv-1",
                List.of(new ChatToolItem("c-samsung", "company", "삼성전자", List.of("c-samsung"), List.of(EV_A, EV_B)),
                        new ChatToolItem(EV_B, "evidence", "허가 없는 기사 제목", List.of(), List.of(EV_B))),
                List.of(EV_A), false, false, null);
        var branch = new ChatBranchContext.Branch("r1", "삼성전자 관련 사건", Set.of(ChatQueryType.Q03), false, List.of(result), false);
        ChatGeneratedAnswer generated = stages.generate(run(root("삼성전자 관련 사건")),
                new ChatBranchContext(List.of(), null, List.of(branch), 20));

        JsonNode sent = calls.getFirst().input().get("branches").get(0);
        assertNull(sent.get("paths"), "a branch without a path read sends no paths");
        assertEquals(JOB + ".1.answer", calls.getFirst().invocationId());
        assertEquals(1, sent.get("evidence").size(), "unreadable evidence is not offered");
        assertEquals("news-provider-1", sent.get("evidence").get(0).get("sourceId").stringValue());
        assertEquals("삼성전자가 HBM을 공급한다.", sent.get("evidence").get(0).get("quote").stringValue());
        assertEquals("c-samsung", sent.get("items").get(0).get("id").stringValue());
        assertEquals(1, sent.get("items").size(), "an evidence item (an article title) is never sent as an item");
        assertTrue(calls.getFirst().input().toString().indexOf("허가 없는 기사 제목") < 0);
        assertEquals(List.of(EV_A), generated.sections().getFirst().evidenceIds());
        assertEquals(List.of("c-samsung"), generated.graphTargetIds());
    }

    @Test
    void theVerifierReadsOneVerdictPerSection() {
        answer = call -> succeeded(call, """
                {"sections":[{"support":null,"prohibitedAdvice":"no"},{"support":"supported","prohibitedAdvice":"hold"}]}""");
        var sections = List.of(new ChatGeneratedAnswer.Section("general_knowledge", "PER은…", List.of("r1"), List.of()),
                new ChatGeneratedAnswer.Section("evidence_grounded", "공급합니다.", List.of("r2"), List.of(EV_A)));
        ChatRun run = run(root("q"));
        ChatSemanticVerdicts verdicts = stages.verify(run, sections, List.of(citation(EV_A, "인용")),
                ChatModels.ServerFacts.withoutTools(run, sections));
        assertEquals(new ChatSemanticVerdicts.Verdict(null, "no"), verdicts.sections().get(0));
        assertEquals(new ChatSemanticVerdicts.Verdict("supported", "hold"), verdicts.sections().get(1));
        assertEquals("news-provider-1", calls.getFirst().input().get("citations").get(0).get("sourceId").stringValue());
    }

    @Test
    void aWebHitIsSentUnderItsProvidersGrant() {
        answer = call -> succeeded(call, """
                {"sections":[{"support":"supported","prohibitedAdvice":"no"}]}""");
        String hit = "web-" + "c".repeat(32);
        var web = new Citation("web_result", hit, "[합성 자료] HBM은 D램을 쌓은 메모리다.", null, null, "synthetic", null, 0, 20,
                "[합성] HBM이란", "news.example.com", null, "https://news.example.com/hbm");
        ChatRun run = run(root("q"));
        var sections = List.of(new ChatGeneratedAnswer.Section("web_reported", "HBM은 D램을 쌓은 메모리라고 보도됐어요.",
                List.of("r1"), List.of(hit)));
        stages.verify(run, sections, List.of(web), ChatModels.ServerFacts.withoutTools(run, sections));
        JsonNode sent = calls.getFirst().input();
        assertEquals("web-search:synthetic", sent.get("citations").get(0).get("sourceId").stringValue());
        assertEquals(hit, sent.get("citations").get(0).get("evidenceId").stringValue());
        assertEquals("web_reported", sent.get("sections").get(0).get("basis").stringValue());
    }

    @Test
    void aZoopDocumentQuoteIsSentUnderTheZoopDocumentGrant() {
        answer = call -> succeeded(call, """
                {"sections":[{"support":"supported","prohibitedAdvice":"no"}]}""");
        var doc = new Citation("zoop_doc", EV_B, "## 2. 보유 기간\n\n탈퇴하면 지웁니다.", null, null, "policy.privacy",
                "2026-10-13.1", 10, 30, "개인정보 처리방침 · 2. 보유 기간", null, null, null);
        ChatRun run = run(root("q"));
        var sections = List.of(new ChatGeneratedAnswer.Section("zoop_documented", "탈퇴하면 지워집니다.",
                List.of("r1"), List.of(EV_B)));
        stages.verify(run, sections, List.of(doc), ChatModels.ServerFacts.withoutTools(run, sections));
        JsonNode sent = calls.getFirst().input();
        assertEquals("zoop-docs", sent.get("citations").get(0).get("sourceId").stringValue());
        assertEquals("zoop_documented", sent.get("sections").get(0).get("basis").stringValue());
    }

    @Test
    void theGeneratorGetsEachPathPairWithItsStatusAndEachStepWithItsOwnQuotedEvidence() {
        answer = call -> succeeded(call, """
                {"sections":[],"insufficientRequirementIds":["r1"],"graphTargetIds":[]}""");
        var step1 = new ChatToolPath.Step("e-1", "iss-hbm", "c-samsung", "INVOLVES", "공급사", List.of(EV_A, EV_B));
        var step2 = new ChatToolPath.Step("e-2", "iss-hbm", "c-nvda", "INVOLVES", null, List.of());
        var found = new ChatToolPath("c-samsung", "c-nvda", ChatToolPath.FOUND, List.of(step1, step2));
        JsonNode cut = pathsSent(found, new ChatToolPath("c-samsung", "c-amd", ChatToolPath.CUT, List.of()));
        JsonNode none = pathsSent(found, new ChatToolPath("c-samsung", "c-amd", ChatToolPath.NONE, List.of()));

        assertEquals(2, cut.size());
        JsonNode first = cut.get(0);
        assertEquals("found", first.get("status").stringValue());
        assertEquals("c-samsung", first.get("fromId").stringValue());
        assertEquals(List.of("e-1", "e-2"), first.get("steps").valueStream().map(s -> s.get("edgeId").stringValue()).toList());
        JsonNode s1 = first.get("steps").get(0);
        assertEquals("iss-hbm", s1.get("sourceId").stringValue());
        assertEquals("INVOLVES", s1.get("relation").stringValue());
        assertEquals("공급사", s1.get("role").stringValue());
        assertEquals(1, s1.get("evidenceIds").size(), "only evidence quoted in the branch is named");
        assertEquals(EV_A, s1.get("evidenceIds").get(0).stringValue());
        assertTrue(first.get("steps").get(1).get("role").isNull());

        assertEquals("cut", cut.get(1).get("status").stringValue());
        assertEquals("none", none.get(1).get("status").stringValue());
        assertEquals(cut.get(0), none.get(0), "the found pair is the same; only the second pair's status tells them apart");
    }

    private JsonNode pathsSent(ChatToolPath... paths) {
        calls.clear();
        var result = new ChatToolResult(ChatToolRegistry.VERSION, "tc-1", "graph.path.read", "gv-1",
                List.of(new ChatToolItem("c-samsung", "company", "삼성전자", List.of("c-samsung"), List.of()),
                        new ChatToolItem("e-1", "edge", "HBM 공급 – 삼성전자", List.of("c-samsung"), List.of(EV_A, EV_B))),
                List.of(EV_A), false, false, null, List.of(paths));
        var branch = new ChatBranchContext.Branch("r1", "삼성전자와 엔비디아의 관계", Set.of(ChatQueryType.Q04), false,
                List.of(result), false);
        stages.generate(run(root("삼성전자와 엔비디아의 관계")), new ChatBranchContext(List.of(), null, List.of(branch), 20));
        return calls.getFirst().input().get("branches").get(0).get("paths");
    }

    @Test
    void stageFailuresMapToTheirFate() {
        ChatRun run = run(root("PER이 뭐야"));
        answer = call -> failed(call, true, true);
        assertEquals(Fate.UNKNOWN, fate(() -> stages.route(run, Set.of())));
        assertTrue(recorded.getLast().startsWith("finish unknown"));
        answer = call -> failed(call, true, false);
        assertEquals(Fate.NOT_SENT, fate(() -> stages.route(run, Set.of())));
        answer = call -> failed(call, false, false);
        assertEquals(Fate.REFUSED, fate(() -> stages.route(run, Set.of())));
        answer = call -> succeeded(call, "{\"requirements\":[]}");
        assertEquals(Fate.NOT_SENT, fate(() -> stages.route(run, Set.of())), "an answer for other requirements is malformed");

        answer = call -> { throw rejection(503); };
        assertEquals(Fate.NOT_SENT, fate(() -> stages.route(run, Set.of())));
        answer = call -> { throw rejection(504); };
        assertEquals(Fate.UNKNOWN, fate(() -> stages.route(run, Set.of())));
        answer = call -> { throw rejection(409); };
        assertEquals(Fate.REFUSED, fate(() -> stages.route(run, Set.of())));
        answer = call -> { throw new AiTransportException(AiOperation.CHAT_STAGE, "r", AiTransportException.Failure.CONNECT_FAILED,
                OptionalInt.empty(), null); };
        assertEquals(Fate.NOT_SENT, fate(() -> stages.route(run, Set.of())));
        answer = call -> { throw new AiTransportException(AiOperation.CHAT_STAGE, "r", AiTransportException.Failure.TIMEOUT,
                OptionalInt.empty(), null); };
        assertEquals(Fate.UNKNOWN, fate(() -> stages.route(run, Set.of())));
    }

    @Test
    void aStageCutOffWhileItsOutcomeIsBeingWrittenIsStillRecorded() throws Exception {
        var writing = new CountDownLatch(1);
        var cutOff = new CountDownLatch(1);
        var writerInterrupted = new AtomicBoolean();
        var stages = stages(new ChatModelRecorder(null, Clock.systemUTC()) {
            @Override
            public String start(String jobId, int attemptNo, String stage, String mode) {
                return "aix-1";
            }

            @Override
            public void finish(String id, String status, String sendState, ChatStageReply.Receipt receipt, String errorCode) {
                writing.countDown();
                try {
                    // The engine's cancellation lands here, in the middle of the write.
                    assertTrue(cutOff.await(5, TimeUnit.SECONDS));
                } catch (InterruptedException e) {
                    writerInterrupted.set(true);
                    return;
                }
                writerInterrupted.set(Thread.currentThread().isInterrupted());
                recorded.add("finish " + status);
            }
        });
        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q02":0.9},"capabilities":{},"prohibitedAdvice":0.0,"dependsOn":null}]}""");
        var restored = new AtomicBoolean();
        Thread stage = Thread.ofPlatform().start(() -> {
            stages.route(run(root("PER이 뭐야")), Set.of());
            restored.set(Thread.currentThread().isInterrupted());
        });

        assertTrue(writing.await(5, TimeUnit.SECONDS));
        stage.interrupt();
        cutOff.countDown();
        stage.join(5000);

        assertEquals(List.of("finish succeeded"), recorded);
        assertFalse(writerInterrupted.get(), "the write never sees the stage's interrupt");
        assertTrue(restored.get(), "the stage thread keeps its interrupt for the engine");
    }

    private static AiServiceErrorException rejection(int status) {
        return new AiServiceErrorException(AiOperation.CHAT_STAGE, "r", status, "some_code", false, Optional.empty(),
                Optional.empty(), Optional.empty(), Optional.empty());
    }

    private static Fate fate(Runnable call) {
        return assertThrows(ChatModels.Failure.class, call::run).fate();
    }
}
