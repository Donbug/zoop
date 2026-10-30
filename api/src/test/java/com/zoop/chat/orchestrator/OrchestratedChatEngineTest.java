package com.zoop.chat.orchestrator;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.BiFunction;

import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatToolCallReservation;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer.Section;
import com.zoop.chat.orchestrator.ChatPlannerTest.Req;
import com.zoop.chat.orchestrator.ChatRouteDecision.Dependency;
import com.zoop.chat.orchestrator.ChatSemanticVerdicts.Verdict;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.tool.ChatBriefingRound;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatSelectionRecord;
import com.zoop.chat.tool.SelectionRuleReadTool;
import com.zoop.chat.tool.ChatTool;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolScope;
import com.zoop.chat.tool.ChatToolUnavailable;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static com.zoop.chat.orchestrator.ChatPlannerTest.req;
import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 orchestration with scripted models (no model, no network) and scripted read tools: the server decides limitations,
 * citations, answer basis and outcome; checks fail closed; deadlines and failures are classified as ZOOP-AIG-001 6.3.3 says.
 */
class OrchestratedChatEngineTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String HYNIX = "KRX:000660";
    private static final String NVDA = "NASDAQ:NVDA";
    private static final String AMD = "NASDAQ:AMD";
    private static final Map<String, String> LABELS = Map.of(HYNIX, "SK하이닉스", NVDA, "NVIDIA", AMD, "AMD");

    private final List<ChatToolRunner> runners = new ArrayList<>();
    private final List<OrchestratedChatEngine> engines = new ArrayList<>();
    private final List<ChatBranchContext> generated = new ArrayList<>();
    private final Map<ChatCapability, BiFunction<ChatToolScope, ChatToolRequest, ChatToolOutput>> tools = new HashMap<>();
    private final Map<String, Citation> readable = new HashMap<>();
    private List<String> issueCompanies = List.of(HYNIX, NVDA);
    private ChatRouteDecision decision;
    private ChatGeneratedAnswer answer;
    private ChatSemanticVerdicts verdicts;
    private RuntimeException routerFailure;
    private RuntimeException generatorFailure;
    private int verifierCalls;
    private ChatModels.ServerFacts verifiedFacts;
    private ChatRun verifiedRun;
    private List<Section> verifiedSections;

    OrchestratedChatEngineTest() {
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> {
            // Like the real adapter: evidence outside the request's scope is never passed on.
            List<ChatToolItem> items = request.targets().stream().filter(LABELS::containsKey)
                    .map(id -> new ChatToolItem(id, "company", LABELS.get(id), List.of(id),
                            request.evidenceScope() == null || request.evidenceScope().contains(evidence(id))
                                    ? List.of(evidence(id)) : List.of())).toList();
            return new ChatToolOutput(scope.graphVersionId(), items,
                    items.stream().flatMap(i -> i.evidenceIds().stream()).toList(), false, false);
        });
        tools.put(ChatCapability.ISSUE_READ, (scope, request) -> {
            List<ChatToolItem> items = issueCompanies.isEmpty() ? List.of()
                    : List.of(new ChatToolItem("iss-1", "issue", "HBM 공급", issueCompanies, List.of("ev-issue")));
            return new ChatToolOutput(scope.graphVersionId(), items, items.isEmpty() ? List.of() : List.of("ev-issue"),
                    false, false);
        });
        for (String id : List.of(HYNIX, NVDA, AMD, "issue")) {
            String evidence = id.equals("issue") ? "ev-issue" : evidence(id);
            readable.put(evidence, new Citation("article", evidence, "인용 " + id, "art-" + id, "v1", null, null, 0, 4,
                    "기사 " + id, "언론사", NOW, "https://example.invalid/" + id));
        }
    }

    @AfterEach
    void tearDown() {
        runners.forEach(ChatToolRunner::close);
        engines.forEach(OrchestratedChatEngine::close);
    }

    @Test
    void aSelectionQuestionIsAnsweredFromTheRecordsAndTheVerifierGetsThemAsFacts() {
        // D-AI-02 Q08: the recorded publication carries no article to cite; the verifier checks the section against it.
        List<ChatToolRequest> asked = new ArrayList<>();
        var publication = new ChatSelectionRecord.Publication("iss-1", "HBM 공급", "v1", 12, 3L, "allow", "admin_review",
                Instant.parse("2026-10-20T05:00:00Z"), List.of(new ChatSelectionRecord.Rule("single-source@1",
                "출처가 기사 1개뿐인 관계 숨기기", "근거 기사 2개 미만인 관계를 숨깁니다.")));
        tools.put(ChatCapability.SELECTION_RULE_READ, (scope, request) -> {
            asked.add(request);
            return new ChatToolOutput(scope.graphVersionId(), List.of(new ChatToolItem("sel-map:iss-1", "selection_record",
                    SelectionRuleReadTool.label(publication), List.of(), List.of())), List.of(), false, false, List.of(),
                    List.of(), List.of(publication));
        });
        decision = ChatPlannerTest.decision(new ChatRouteDecision.Requirement("r1", "이 사건은 왜 지도에 있어", true,
                Map.of(ChatQueryType.Q08, 0.9), Map.of("selectionRule.read", 0.9), List.of("iss-1"), 0.0, null));
        answer = new ChatGeneratedAnswer(List.of(grounded("이 사건은 관리자 검수에서 공개 승인됐어요.", List.of("r1"))),
                List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));

        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));

        assertEquals("answered", result.outcome());
        assertTrue(result.citations().isEmpty(), "a record is no article");
        assertEquals(List.of(List.of(ChatBriefingRound.LATEST, "iss-1")),
                asked.stream().map(ChatToolRequest::targets).toList());
        var fact = assertInstanceOf(ChatModels.PublicationFact.class,
                verifiedFacts.forRequest(verifiedRun, verifiedSections).getFirst().getFirst());
        assertEquals("r1", fact.requirementId());
        assertEquals("admin_review", fact.decisionPath());
        assertEquals(List.of("single-source@1"), fact.rules().stream().map(ChatModels.PublicationRule::ruleId).toList());
    }

    @Test
    void aBriefingQuestionReadsTheRoundItsOwnWordsName() {
        // D-AI-02 Q06: "오늘 아침" is that day's morning round (asked 1970-01-01 09:00 KST), never a model's choice.
        List<ChatToolRequest> briefing = new ArrayList<>();
        tools.put(ChatCapability.BRIEFING_READ, (scope, request) -> {
            briefing.add(request);
            return new ChatToolOutput("briefing:br-1", List.of(new ChatToolItem("iss-1", "briefing_item",
                    "[1970-01-01 출근 브리핑 1위] HBM 공급 — 선정 이유: 연결", List.of(HYNIX), List.of(evidence(HYNIX)))),
                    List.of(evidence(HYNIX)), false, false);
        });
        decision = ChatPlannerTest.decision(new ChatRouteDecision.Requirement("r1", "오늘 아침 브리핑에 뭐 나왔어", true,
                Map.of(ChatQueryType.Q06, 0.9), Map.of("briefing.read", 0.9), List.of(), 0.0, null));
        answer = new ChatGeneratedAnswer(List.of(grounded("오늘 출근 브리핑에는 HBM 공급 사건이 있었어요.", List.of("r1"),
                evidence(HYNIX))), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));

        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));

        assertEquals("answered", result.outcome());
        assertEquals(List.of(List.of("briefing:1970-01-01:morning")), briefing.stream().map(ChatToolRequest::targets).toList());
        assertEquals(List.of(readable.get(evidence(HYNIX))), result.citations());
    }

    @Test
    void aGeneralConceptIsOneGeneralSectionWithTheServerNoticeAndNoSources() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.95), Map.of()));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 고대역폭 메모리입니다.", "r1")), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no")));
        var control = new Control(Duration.ofSeconds(60));

        ChatResult result = completed(engine().answer(run(), control));
        assertEquals("answered", result.outcome());
        assertEquals("general_knowledge", result.answerBasis());
        assertEquals(ChatAnswerCheck.GENERAL_NOTICE + " HBM은 고대역폭 메모리입니다.", result.answer());
        assertTrue(result.sources().isEmpty() && result.citations().isEmpty() && result.limitations().isEmpty());
        assertEquals(3, control.modelCalls, "router, generator and verifier, each announced");
        assertEquals(List.of("writing", "verifying"), control.phases);
        assertTrue(control.reserved.isEmpty());
    }

    @Test
    void everyPathReadCarriesTheFirstTargetWhenTheTargetsAreSplit() {
        List<List<String>> asked = Collections.synchronizedList(new ArrayList<>());
        tools.put(ChatCapability.GRAPH_PATH_READ, (scope, request) -> {
            asked.add(request.targets());
            return new ChatToolOutput(scope.graphVersionId(), List.of(), List.of(), false, false);
        });
        answer = new ChatGeneratedAnswer(List.of(), List.of("r1"), List.of());
        verdicts = new ChatSemanticVerdicts(List.of());
        for (int count : List.of(6, 7)) {
            asked.clear();
            List<String> targets = java.util.stream.IntStream.range(0, count).mapToObj(i -> "KRX:00000" + i).toList();
            decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q04, 0.9), Map.of("graph.path.read", 0.9),
                    targets));
            engine().answer(run(), new Control(Duration.ofSeconds(60)));
            assertEquals(Set.of(targets.subList(0, 5), List.copyOf(
                    java.util.stream.Stream.concat(java.util.stream.Stream.of(targets.getFirst()),
                            targets.subList(5, count).stream()).toList())), Set.copyOf(asked),
                    count + " targets: the anchor goes with the rest, never a later target in its place");
        }
    }

    @Test
    void aMixedAnswerGetsServerCitationsSourcesTargetsAndAppliedScope() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 메모리입니다.", "r1"),
                grounded("SK하이닉스는 HBM을 공급합니다.", List.of("r2"), evidence(HYNIX))), List.of(), List.of(HYNIX));
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no"), new Verdict("supported", "no")));
        var control = new Control(Duration.ofSeconds(60));

        var outcome = assertInstanceOf(ChatEngineOutcome.Completed.class, engine().answer(run(), control));
        ChatResult result = outcome.result();
        assertEquals("mixed", result.answerBasis());
        assertEquals(List.of(readable.get(evidence(HYNIX))), result.citations(), "the citation is the evidence record's own");
        assertEquals(List.of("art-" + HYNIX), result.sources());
        assertEquals(List.of(new GraphTarget(HYNIX, "company")), result.graphTargets());
        assertEquals(List.of(HYNIX), result.applied().companies().stream().map(c -> c.id()).toList());
        assertEquals("v1", result.applied().graphVersion());
        assertEquals(List.of("retrieving", "writing", "verifying"), control.phases);
        assertEquals(List.of(evidence(HYNIX)), generated.getFirst().branches().get(1).results().getFirst().evidenceIds());
        assertEquals("tools", outcome.routeSummary().path("requirements").get(1).path("mode").asString());
    }

    @Test
    void aConceptAskedWithAFactInOneRequirementIsAnsweredBesideTheFact() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9),
                Map.of("company.read", 0.9), List.of(HYNIX)));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 메모리 칩을 쌓은 메모리입니다.", "r1-c"),
                grounded("SK하이닉스는 HBM을 공급합니다.", List.of("r1"), evidence(HYNIX))), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no"), new Verdict("supported", "no")));

        var outcome = assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine().answer(run(), new Control(Duration.ofSeconds(60))));
        ChatResult result = outcome.result();
        assertEquals("answered", result.outcome());
        assertEquals("mixed", result.answerBasis());
        assertTrue(result.limitations().isEmpty());
        assertEquals("complete", result.answerStatus());
        assertTrue(result.notices().isEmpty());
        assertEquals(List.of(readable.get(evidence(HYNIX))), result.citations());

        var concept = generated.getFirst().branches().get(1);
        assertEquals("r1-c", concept.requirementId());
        assertTrue(concept.general() && concept.results().isEmpty());
        assertEquals("r1", concept.parent());
        assertEquals(List.of("SK하이닉스"), concept.avoidNames(), "what the parent's read returned");
        var route = outcome.routeSummary().path("requirements").get(1);
        assertEquals("general", route.path("mode").asString());
        assertEquals("concept", route.path("origin").asString());
        assertEquals("r1", route.path("parent").asString());
    }

    @Test
    void whenTheFactPartHasNoEvidenceOrNoLookupTheConceptIsStillAnswered() {
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> new ChatToolOutput(scope.graphVersionId(),
                List.of(new ChatToolItem(HYNIX, "company", "SK하이닉스", List.of(HYNIX), List.of())), List.of(), false, false));
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9),
                Map.of("company.read", 0.9), List.of(HYNIX)));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 메모리 칩을 쌓은 메모리입니다.", "r1-c")), List.of("r1"),
                List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no")));
        ChatResult noEvidence = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("answered", noEvidence.outcome(), "it used to be insufficient_evidence with no concept either");
        assertEquals("general_knowledge", noEvidence.answerBasis());
        assertEquals(List.of("evidence_insufficient"), noEvidence.limitations().stream().map(l -> l.kind()).toList());
        assertEquals("요구 r1", noEvidence.limitations().getFirst().label());
        assertEquals("partial", noEvidence.answerStatus(), "the fact part is unanswered");

        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9), Map.of()));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 메모리 칩을 쌓은 메모리입니다.", "r1-c")), List.of(),
                List.of());
        var control = new Control(Duration.ofSeconds(60));
        ChatResult noLookup = completed(engine().answer(run(), control));
        assertEquals("answered", noLookup.outcome(), "it used to be guidance");
        assertEquals(List.of("out_of_scope"), noLookup.limitations().stream().map(l -> l.kind()).toList());
        assertEquals(3, control.modelCalls, "like a pure concept: router, generator and verifier");
        assertTrue(control.reserved.isEmpty());
    }

    @Test
    void aConceptSectionThatBreaksAGeneralRuleIsDroppedWithoutFailingTheAnswer() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9),
                Map.of("company.read", 0.9), List.of(HYNIX)));
        for (String text : List.of("SK 하이닉스의 HBM은 메모리입니다.", "HBM 시장은 2026년에 커졌습니다.")) {
            answer = new ChatGeneratedAnswer(List.of(general(text, "r1-c"),
                    grounded("SK하이닉스는 HBM을 공급합니다.", List.of("r1"), evidence(HYNIX))), List.of(), List.of());
            verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));
            var outcome = assertInstanceOf(ChatEngineOutcome.Completed.class,
                    engine().answer(run(), new Control(Duration.ofSeconds(60))));
            assertEquals("evidence_grounded", outcome.result().answerBasis(), text);
            assertEquals(1, outcome.result().sections().size(), text);
            assertTrue(outcome.result().limitations().isEmpty(), "the concept is the server's own addition: " + text);
            assertEquals("r1-c", outcome.routeSummary().path("droppedGeneral").get(0).asString(), text);
        }

        answer = new ChatGeneratedAnswer(List.of(general("HBM 시장은 2026년에 커졌습니다.", "r1-c")), List.of("r1"),
                List.of());
        verdicts = new ChatSemanticVerdicts(List.of());
        ChatResult nothingLeft = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("insufficient_evidence", nothingLeft.outcome());
        assertEquals("guidance", nothingLeft.answerStatus());

        answer = new ChatGeneratedAnswer(List.of(general("HBM은 메모리입니다. 지금 매수하세요.", "r1-c"),
                grounded("SK하이닉스는 HBM을 공급합니다.", List.of("r1"), evidence(HYNIX))), List.of(), List.of());
        assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));

        // A general section of the router's own requirement still fails the answer.
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()));
        answer = new ChatGeneratedAnswer(List.of(general("HBM 시장은 2026년에 커졌습니다.", "r1")), List.of(), List.of());
        assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
    }

    @Test
    void anAnswerWithNothingToStandOnSaysWhyAndShowsWhatWasLookedAt() {
        var scoped = tools.get(ChatCapability.COMPANY_READ);
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        answer = new ChatGeneratedAnswer(List.of(), List.of("r1"), List.of());
        verdicts = new ChatSemanticVerdicts(List.of());

        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> new ChatToolOutput(scope.graphVersionId(),
                List.of(new ChatToolItem(HYNIX, "company", "SK하이닉스", List.of(HYNIX), List.of())), List.of(), false, false));
        var found = assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("insufficient_evidence", found.result().outcome());
        assertEquals(ChatResults.insufficientReason(run(), ChatResults.InsufficientCause.EVIDENCE_INSUFFICIENT, false),
                found.result().reason());
        assertTrue(found.result().reason().startsWith("관련 항목은 찾았지만"), found.result().reason());
        assertEquals(List.of("SK하이닉스"), found.result().applied().companies().stream().map(c -> c.label()).toList(),
                "the scope shows what was looked at, not 'none'");
        assertEquals("evidence_insufficient", found.routeSummary().path("reason").asString());

        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> new ChatToolOutput(scope.graphVersionId(), List.of(),
                List.of(), false, false));
        var none = assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertTrue(none.result().reason().startsWith("조회한 범위에서 관련된 공개 자료를 찾지 못했어요."), none.result().reason());
        assertEquals("nothing_found", none.routeSummary().path("reason").asString());

        tools.put(ChatCapability.COMPANY_READ, scoped);
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)));
        var narrowed = ChatPlannerTest.run(0, "v1", List.of(HYNIX), List.of("ev-other"), List.of("ev-other"));
        ChatResult selection = completed(engine().answer(narrowed, new Control(Duration.ofSeconds(60))));
        assertEquals("insufficient_evidence", selection.outcome());
        assertTrue(selection.reason().endsWith("선택을 해제하고 다시 물으면 더 넓게 찾아볼 수 있어요."), selection.reason());

        // The same selection, but the question names another company: that read was not narrowed, so neither is the hint.
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> new ChatToolOutput(scope.graphVersionId(), List.of(),
                List.of(), false, false));
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(NVDA)));
        ChatResult elsewhere = completed(engine().answer(narrowed, new Control(Duration.ofSeconds(60))));
        assertEquals("insufficient_evidence", elsewhere.outcome());
        assertFalse(elsewhere.reason().contains("선택한 근거 안에서만"), elsewhere.reason());
        assertTrue(elsewhere.reason().endsWith("지도에서 대상을 고른 뒤 다시 물어봐 주세요."), elsewhere.reason());
    }

    @Test
    void anInvestmentDecisionIsALimitationOrGuidanceButNeverGenerated() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                req("r2", Map.of(ChatQueryType.Q02, 0.9), Map.of()).withAdvice(0.97));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 메모리입니다.", "r1")), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no")));
        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals(List.of("investment_advice"), result.limitations().stream().map(l -> l.kind()).toList());
        assertEquals("요구 r2", result.limitations().getFirst().label());
        assertEquals("partial", result.answerStatus());
        assertEquals(List.of("r1"), generated.getFirst().branches().stream().map(b -> b.requirementId()).toList());

        generated.clear();
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()).withAdvice(0.97));
        var control = new Control(Duration.ofSeconds(60));
        ChatResult guidance = completed(engine().answer(run(), control));
        assertEquals("guidance", guidance.outcome());
        assertEquals(ChatResults.reason("investment_advice"), guidance.reason());
        assertEquals(1, control.modelCalls);
        assertTrue(generated.isEmpty());
    }

    @Test
    void moreCompaniesThanTheCheckpointAllowsAskWhichOnesBeforeTheNextStage() {
        issueCompanies = List.of(HYNIX, NVDA, AMD);
        decision = dependent("exactly", 2);
        var control = new Control(Duration.ofSeconds(60));

        ChatResult result = completed(engine().answer(run(), control));
        assertEquals("clarification", result.outcome());
        // An issue lists its companies by id only, so the labels are ids until the read carries company names.
        assertEquals(List.of(HYNIX + " · " + NVDA, HYNIX + " · " + AMD, NVDA + " · " + AMD),
                result.choices().stream().map(c -> c.label()).toList());
        assertTrue(result.choices().stream().allMatch(c -> "scope".equals(c.kind())));
        assertEquals(1, control.reserved.size(), "the dependent stage never ran");
        assertTrue(generated.isEmpty());
        assertEquals(1, control.modelCalls);
    }

    @Test
    void fewerCompaniesThanTheCheckpointNeedsLimitTheDependentRequirementOnly() {
        issueCompanies = List.of(HYNIX);
        decision = dependent("exactly", 2);
        answer = new ChatGeneratedAnswer(List.of(grounded("HBM 공급 사건이 있습니다.", List.of("r1"), "ev-issue")),
                List.of(), List.of("iss-1"));
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));

        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("answered", result.outcome());
        assertEquals(List.of("precondition_unmet"), result.limitations().stream().map(l -> l.kind()).toList());
        assertEquals(List.of(new GraphTarget("iss-1", "issue")), result.graphTargets());
    }

    @Test
    void aMetCheckpointRunsTheNextStageOnWhatWasFound() {
        decision = dependent("exactly", 2);
        answer = new ChatGeneratedAnswer(List.of(grounded("사건", List.of("r1"), "ev-issue"),
                grounded("두 회사", List.of("r2"), evidence(HYNIX), evidence(NVDA))), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no"), new Verdict("supported", "no")));
        var control = new Control(Duration.ofSeconds(60));

        ChatResult result = completed(engine().answer(run(), control));
        assertEquals("answered", result.outcome());
        assertEquals(2, control.reserved.size());
        assertEquals("company.read", control.reserved.get(1).capabilityId());
        assertEquals(3, result.citations().size());
    }

    @Test
    void aLookupThatFoundNothingMaySaySoWithoutEvidence() {
        issueCompanies = List.of();
        decision = dependent("exactly", 2);
        answer = new ChatGeneratedAnswer(List.of(grounded("조회 범위에서 해당 사건은 없습니다.", List.of("r1"))), List.of(),
                List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));
        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("answered", result.outcome());
        assertTrue(generated.getFirst().branches().getFirst().noneFound());
        assertEquals(List.of("precondition_unmet"), result.limitations().stream().map(l -> l.kind()).toList());
    }

    @Test
    void aToolFailureThatLeavesNothingAnsweredEndsTheRun() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> { throw new ChatToolUnavailable("snapshot"); });
        assertFailed("transient", null, true, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> { throw new IllegalStateException("bug"); });
        assertFailed("internal", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertTrue(generated.isEmpty());
    }

    @Test
    void aPassingToolFaultLeavesOnlyItsRequirementUnansweredAndTheRestIsAPartialAnswer() {
        // D-AI-02: the member gets what could be read and is told which part could not be.
        decision = ChatPlannerTest.decision(
                req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1")));
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> { throw new ChatToolUnavailable("snapshot"); });
        answer = new ChatGeneratedAnswer(List.of(grounded("HBM 공급 사건이 있습니다.", List.of("r2"), "ev-issue")),
                List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));

        var outcome = assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine().answer(run(), new Control(Duration.ofSeconds(60))));
        ChatResult result = outcome.result();
        assertEquals("answered", result.outcome());
        assertEquals("partial", result.answerStatus());
        assertEquals(List.of("tool_unavailable"), result.limitations().stream().map(l -> l.kind()).toList());
        assertEquals("요구 r1", result.limitations().getFirst().label());
        assertEquals(List.of("r2"), generated.getFirst().branches().stream().map(b -> b.requirementId()).toList(),
                "the unanswered requirement is no branch: nothing is written about it");
        assertEquals("r1", outcome.routeSummary().path("toolFaults").get(0).asString());

        // A timeout is the same passing fault.
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> {
            try {
                Thread.sleep(10_000);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
            return new ChatToolOutput(scope.graphVersionId(), List.of(), List.of(), false, false);
        });
        ChatResult late = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals(List.of("tool_unavailable"), late.limitations().stream().map(l -> l.kind()).toList());
    }

    @Test
    void anAdapterFaultInOneRequirementStillEndsTheRun() {
        decision = ChatPlannerTest.decision(
                req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1")));
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> { throw new IllegalStateException("bug"); });
        assertFailed("internal", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertTrue(generated.isEmpty(), "a bug is not passed off as a partial answer");
    }

    @Test
    void aFaultedSourceLeavesItsDependentUnavailableNotUnderItsCondition() {
        // The second stage cannot run when its source could not be read: that is the fault, not a checkpoint miss.
        decision = dependent("exactly", 2);
        tools.put(ChatCapability.ISSUE_READ, (scope, request) -> { throw new ChatToolUnavailable("snapshot"); });
        var control = new Control(Duration.ofSeconds(60));
        assertFailed("transient", null, true, engine().answer(run(), control));
        assertEquals(1, control.reserved.size(), "the dependent stage never ran");

        // The source read and the dependent stage faulted: the source is answered, the dependent is unavailable.
        tools.put(ChatCapability.ISSUE_READ, (scope, request) -> new ChatToolOutput(scope.graphVersionId(),
                List.of(new ChatToolItem("iss-1", "issue", "HBM 공급", List.of(HYNIX, NVDA), List.of("ev-issue"))),
                List.of("ev-issue"), false, false));
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> { throw new ChatToolUnavailable("snapshot"); });
        answer = new ChatGeneratedAnswer(List.of(grounded("HBM 공급 사건이 있습니다.", List.of("r1"), "ev-issue")),
                List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));
        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("partial", result.answerStatus());
        assertEquals(List.of("tool_unavailable"), result.limitations().stream().map(l -> l.kind()).toList());
        assertEquals("요구 r2", result.limitations().getFirst().label());
    }

    @Test
    void aFaultIsNeverHiddenAsMissingEvidenceWhenWhatWasReadIsHeld() {
        decision = ChatPlannerTest.decision(
                req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1")));
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> { throw new ChatToolUnavailable("snapshot"); });
        answer = new ChatGeneratedAnswer(List.of(grounded("HBM 공급 사건이 있습니다.", List.of("r2"), "ev-issue")),
                List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("hold", "no")));
        assertFailed("transient", null, true, engine().answer(run(), new Control(Duration.ofSeconds(60))));
    }

    @Test
    void aFailedDeterministicCheckIsValidationFailedAndTheVerifierIsNeverCalled() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)));
        verdicts = new ChatSemanticVerdicts(List.of());
        List<ChatGeneratedAnswer> bad = List.of(
                // evidence the tool never passed on
                new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("사실", List.of("r2"), "ev-other")),
                        List.of(), List.of()),
                // r2 is neither answered nor declared insufficient
                new ChatGeneratedAnswer(List.of(general("개념", "r1")), List.of(), List.of()),
                // a general section citing evidence
                new ChatGeneratedAnswer(List.of(new Section("general_knowledge", "개념", List.of("r1"), List.of(evidence(HYNIX))),
                        grounded("사실", List.of("r2"), evidence(HYNIX))), List.of(), List.of()),
                // an evidence section without evidence while something was found
                new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("사실", List.of("r2"))), List.of(), List.of()),
                // recommendation wording
                new ChatGeneratedAnswer(List.of(general("지금 SK하이닉스를 매수하세요.", "r1"),
                        grounded("사실", List.of("r2"), evidence(HYNIX))), List.of(), List.of()),
                // a map target no tool returned
                new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("사실", List.of("r2"), evidence(HYNIX))),
                        List.of(), List.of(NVDA)),
                // answered and declared insufficient at once
                new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("사실", List.of("r2"), evidence(HYNIX))),
                        List.of("r2"), List.of()));
        for (var candidate : bad) {
            answer = candidate;
            assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        }
        assertEquals(0, verifierCalls);
    }

    @Test
    void evidenceThatIsNoLongerReadableCannotBeCited() {
        decision = ChatPlannerTest.decision(req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        answer = new ChatGeneratedAnswer(List.of(grounded("사실", List.of("r2"), evidence(HYNIX))), List.of(), List.of());
        readable.remove(evidence(HYNIX));
        assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals(0, verifierCalls);
    }

    @Test
    void verdictsBlockContradictionsAndDropHeldRequirements() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)),
                req("r3", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(NVDA)));
        answer = new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("하이닉스", List.of("r2"), evidence(HYNIX)),
                grounded("엔비디아", List.of("r3"), evidence(NVDA)),
                grounded("둘을 잇는 문장", List.of("r2", "r3"), evidence(HYNIX), evidence(NVDA))), List.of(),
                List.of(HYNIX, NVDA));
        var supported = new Verdict("supported", "no");

        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no"), new Verdict("contradicted", "no"), supported,
                supported));
        assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "yes"), supported, supported, supported));
        assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));

        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no"), new Verdict("hold", "no"), supported,
                supported));
        ChatResult held = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("answered", held.outcome());
        assertEquals(List.of("개념", "엔비디아"), held.sections().stream()
                .map(s -> s.text().replace(ChatAnswerCheck.GENERAL_NOTICE + " ", "")).toList(),
                "r2 and the section joining it are gone; r3 keeps its own section");
        assertEquals("mixed", held.answerBasis());
        assertEquals(List.of(new GraphTarget(NVDA, "company")), held.graphTargets(),
                "a target only the dropped requirement returned is gone");
        assertEquals(List.of(evidence(NVDA)), held.citations().stream().map(Citation::evidenceId).toList());
        assertEquals(List.of("evidence_insufficient"), held.limitations().stream().map(l -> l.kind()).toList());
        assertEquals("요구 r2", held.limitations().getFirst().label());
        assertEquals("이 부분은 답변 내용이 근거와 맞는지 충분히 확인하지 못해 뺐어요.", held.limitations().getFirst().message(),
                "the kind stays, the message says why");

        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "hold"), new Verdict("hold", "no"),
                new Verdict("hold", "no"), supported));
        ChatResult none = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("insufficient_evidence", none.outcome());
        assertEquals("none", none.answerBasis());
        assertTrue(none.reason().startsWith("근거는 찾았지만"), none.reason());
        assertEquals(List.of("SK하이닉스", "NVIDIA"), none.applied().companies().stream().map(c -> c.label()).toList());

        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no")));
        assertFailed("transient", "provider_error", true, engine().answer(run(), new Control(Duration.ofSeconds(60))));
    }

    @Test
    void aModelStageStartsOnlyWhenTheTimeLeftCoversItAndEverythingAfterIt() {
        decision = ChatPlannerTest.decision(req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var tooLate = new Control(Duration.ofSeconds(52));
        assertFailed("transient", "deadline_guard", true, engine().answer(run(), tooLate));
        assertEquals(0, tooLate.modelCalls);

        // Enough for router + generation + verification + server (53 s), not for tools + generation + verification + server (54 s).
        var noTools = new Control(Duration.ofSeconds(53));
        assertFailed("transient", "deadline_guard", true, engine().answer(run(), noTools));
        assertEquals(1, noTools.modelCalls);
        assertTrue(noTools.reserved.isEmpty());
    }

    @Test
    void aTokenLimitAsksToNarrowTheQuestionInsteadOfRerunningIt() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()));
        routerFailure = new ChatModels.Failure(ChatModels.Failure.Fate.REFUSED, ChatModels.INPUT_BUDGET_EXCEEDED, "input");
        assertFailed("budget_exceeded", "context_too_large", false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        routerFailure = new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, ChatModels.OUTPUT_BUDGET_EXCEEDED, "output");
        assertFailed("budget_exceeded", "output_limit", false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
    }

    @Test
    void modelFailuresAreRerunOnlyWhenNothingMayHaveBeenProcessed() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()));
        routerFailure = new ChatModels.Failure(ChatModels.Failure.Fate.UNKNOWN, "timed out after sending");
        assertFailed("transient", "response_unknown", false, engine().answer(run(), new Control(Duration.ofSeconds(60))));

        routerFailure = null;
        generatorFailure = new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, "connection refused");
        assertFailed("transient", "provider_error", true, engine().answer(run(), new Control(Duration.ofSeconds(60))));
    }

    @Test
    void evidenceTheMemberNarrowedToIsTheOnlyEvidenceTheAnswerCanCite() {
        decision = ChatPlannerTest.decision(req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)));
        var narrowed = ChatPlannerTest.run(0, "v1", List.of(HYNIX, NVDA), List.of(evidence(HYNIX)),
                List.of(evidence(HYNIX)));
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));

        answer = new ChatGeneratedAnswer(List.of(grounded("엔비디아", List.of("r2"), evidence(NVDA))), List.of(), List.of());
        var control = new Control(Duration.ofSeconds(60));
        assertFailed("validation_failed", null, false, engine().answer(narrowed, control));
        assertTrue(control.reserved.getFirst().requestMeta().contains(evidence(HYNIX)), "the scope is part of the record");

        answer = new ChatGeneratedAnswer(List.of(grounded("하이닉스", List.of("r2"), evidence(HYNIX))), List.of(), List.of());
        ChatResult result = completed(engine().answer(narrowed, new Control(Duration.ofSeconds(60))));
        assertEquals(List.of(evidence(HYNIX)), result.citations().stream().map(Citation::evidenceId).toList());
    }

    @Test
    void theAppliedScopeSaysWhenTheQuestionReplacedTheSelection() {
        answer = new ChatGeneratedAnswer(List.of(grounded("사실", List.of("r2"), evidence(HYNIX))), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));
        decision = ChatPlannerTest.decision(req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));

        var selectedOther = ChatPlannerTest.run(0, "v1", List.of(NVDA));
        assertTrue(completed(engine().answer(selectedOther, new Control(Duration.ofSeconds(60))))
                .applied().questionOverrodeContext());
        var selectedSame = ChatPlannerTest.run(0, "v1", List.of(HYNIX));
        assertFalse(completed(engine().answer(selectedSame, new Control(Duration.ofSeconds(60))))
                .applied().questionOverrodeContext());
        assertFalse(completed(engine().answer(run(), new Control(Duration.ofSeconds(60))))
                .applied().questionOverrodeContext(), "nothing was selected, so nothing was replaced");
    }

    @Test
    void aModelStageThatRunsPastItsLimitIsInterruptedAndNeverRerun() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()));
        var interrupted = new java.util.concurrent.CountDownLatch(1);
        ChatModels.Generator slow = (run, context) -> {
            try {
                Thread.sleep(5_000);
            } catch (InterruptedException stop) {
                interrupted.countDown();
            }
            return new ChatGeneratedAnswer(List.of(general("늦은 답", "r1")), List.of(), List.of());
        };
        var limits = new OrchestratedChatEngine.StageLimits(Duration.ofMillis(200), Duration.ofMillis(200),
                Duration.ofMillis(200), Duration.ofMillis(200), Duration.ofMillis(200));
        var control = new Control(Duration.ofSeconds(60));
        try (var engine = engine(slow, limits)) {
            assertFailed("transient", "response_unknown", false, engine.answer(run(), control));
        }
        assertEquals(2, control.modelCalls, "the generator was announced, so the run counts as having called a model");
        assertDoesNotThrow(() -> assertTrue(interrupted.await(2, java.util.concurrent.TimeUnit.SECONDS)));
        assertEquals(0, verifierCalls);
    }

    @Test
    void aPolicyQuestionIsAnsweredFromTheApprovedPoliciesWithoutAGraph() {
        List<List<String>> asked = Collections.synchronizedList(new ArrayList<>());
        tools.put(ChatCapability.ZOOP_POLICY_READ, (scope, request) -> {
            asked.add(request.targets());
            return new ChatToolOutput("zoop-docs/policy.privacy@2026-10-13.1", List.of(new ChatToolItem("policy.privacy",
                    "zoop_doc", "개인정보 처리방침", List.of(), List.of("ev-doc"))), List.of("ev-doc"), false, false);
        });
        readable.put("ev-doc", new Citation("zoop_doc", "ev-doc", "## 2. 보유 기간과 파기\n\n탈퇴하면 지웁니다.", null, null,
                "policy.privacy", "2026-10-13.1", 100, 125, "개인정보 처리방침 · 2. 보유 기간과 파기", null, null, null));
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q01, 0.9), Map.of("zoopPolicy.read", 0.9)));
        answer = new ChatGeneratedAnswer(List.of(new Section("zoop_documented", "탈퇴하면 대화 기록이 지워집니다.",
                List.of("r1"), List.of("ev-doc"))), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));

        ChatResult result = completed(engine().answer(ChatPlannerTest.run(0, null), new Control(Duration.ofSeconds(60))));
        assertEquals("answered", result.outcome());
        assertEquals("zoop_documented", result.answerBasis());
        assertEquals(List.of("zoop_doc"), result.citations().stream().map(Citation::sourceKind).toList());
        assertTrue(result.sources().isEmpty(), "a ZOOP document is not an article source");
        assertEquals(List.of(com.zoop.chat.service.ChatZoopDocs.POLICIES), asked, "the fixed policies, in one call");

        // The read passed it on as a ZOOP document, but the record now says otherwise: the answer cannot stand on it.
        readable.put("ev-doc", readable.get(evidence(HYNIX)));
        assertFailed("validation_failed", null, false,
                engine().answer(ChatPlannerTest.run(0, null), new Control(Duration.ofSeconds(60))));
    }

    @Test
    void aNarrowedEvidenceSelectionBoundsTheCompanyReadButNotTheFixedPolicies() {
        List<ChatToolRequest> asked = Collections.synchronizedList(new ArrayList<>());
        tools.put(ChatCapability.ZOOP_POLICY_READ, (scope, request) -> {
            asked.add(request);
            // Like the real adapter: evidence outside the request's scope is never passed on.
            List<String> evidence = request.evidenceScope() == null || request.evidenceScope().contains("ev-doc")
                    ? List.of("ev-doc") : List.of();
            return new ChatToolOutput("zoop-docs/policy.privacy@2026-10-13.1", List.of(new ChatToolItem("policy.privacy",
                    "zoop_doc", "개인정보 처리방침", List.of(), evidence)), evidence, false, false);
        });
        var companyRead = tools.get(ChatCapability.COMPANY_READ);
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> {
            asked.add(request);
            return companyRead.apply(scope, request);
        });
        readable.put("ev-doc", new Citation("zoop_doc", "ev-doc", "## 2. 보유 기간과 파기\n\n탈퇴하면 지웁니다.", null, null,
                "policy.privacy", "2026-10-13.1", 100, 125, "개인정보 처리방침 · 2. 보유 기간과 파기", null, null, null));
        // One Q01+Q03 requirement with no company named: its targets come from the selection, narrowed to one evidence.
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q01, 0.9, ChatQueryType.Q03, 0.9),
                Map.of("zoopPolicy.read", 0.9, "company.read", 0.9)));
        answer = new ChatGeneratedAnswer(List.of(new Section("zoop_documented", "탈퇴하면 대화 기록이 지워집니다.",
                List.of("r1"), List.of("ev-doc")), grounded("SK하이닉스는 HBM을 공급합니다.", List.of("r1"), evidence(HYNIX))),
                List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no"), new Verdict("supported", "no")));
        var run = ChatPlannerTest.run(0, "v1", List.of(HYNIX), List.of(evidence(HYNIX)), List.of(evidence(HYNIX)));

        ChatResult result = completed(engine().answer(run, new Control(Duration.ofSeconds(60))));
        var policy = asked.stream().filter(r -> r.capabilityId().equals("zoopPolicy.read")).toList();
        var company = asked.stream().filter(r -> r.capabilityId().equals("company.read")).toList();
        assertEquals(1, policy.size());
        assertNull(policy.getFirst().evidenceScope(), "the article selection does not bound the fixed policies");
        assertEquals(List.of(evidence(HYNIX)), company.getFirst().evidenceScope(), "it still bounds the selected company");
        assertEquals("answered", result.outcome());
        assertEquals("mixed", result.answerBasis());
        assertEquals(Set.of("zoop_doc", "article"),
                result.citations().stream().map(Citation::sourceKind).collect(java.util.stream.Collectors.toSet()));
    }

    @Test
    void longGraphLabelsKeepTheirIdentityAndReachVerification() {
        String name = "가".repeat(298) + "\uD840\uDC00" + "끝".repeat(20);
        tools.put(ChatCapability.GRAPH_VERSION_DIFF, (scope, query) -> new ChatToolOutput("v0.." + scope.graphVersionId(),
                List.of(new ChatToolItem("edge-stable", "edge", "[새로 생김] " + name, List.of(HYNIX),
                        List.of("ev-issue"))), List.of("ev-issue"), false, false));
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q05, 0.9),
                Map.of("graph.version.diff", 0.9), List.of(HYNIX)));
        answer = new ChatGeneratedAnswer(List.of(grounded("조회된 관계 변경입니다.", List.of("r1"), "ev-issue")),
                List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("hold", "no")));
        assertEquals("insufficient_evidence", completed(engine().answer(run(), new Control(Duration.ofSeconds(60)))).outcome());
        var fact = assertInstanceOf(ChatModels.ComparisonFact.class,
                verifiedFacts.forRequest(verifiedRun, verifiedSections).getFirst().getFirst());
        assertEquals(List.of(new ChatModels.GraphChange("edge-stable", "edge",
                "가".repeat(298) + "\uD840\uDC00…", "added")), fact.changes());
        assertFalse(fact.truncated(), "shortening a display name does not remove a change");
    }

    @Test
    void serverFactsStayOnTheParentRequirementAndRejectForeignRunsOrSections() {
        tools.put(ChatCapability.PORTFOLIO_SCOPE_READ, (scope, query) -> new ChatToolOutput("member-scope",
                List.of(new ChatToolItem(HYNIX, "company", "SK하이닉스 (보유)", List.of(HYNIX), List.of()),
                        new ChatToolItem(NVDA, "company", "NVIDIA (관심)", List.of(NVDA), List.of())),
                List.of(), true, false));
        tools.put(ChatCapability.GRAPH_VERSION_DIFF, (scope, query) -> new ChatToolOutput("v0.." + scope.graphVersionId(),
                List.of(new ChatToolItem("iss-new", "issue", "[새로 생김] 공급 계약", List.of(HYNIX), List.of("ev-issue")),
                        new ChatToolItem("iss-old", "issue", "[사라짐] 이전 사건", List.of(NVDA), List.of())),
                List.of("ev-issue"), true, false));
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q05, 0.9, ChatQueryType.Q07, 0.9),
                Map.of("portfolio.scope.read", 0.9, "graph.version.diff", 0.9)));
        answer = new ChatGeneratedAnswer(List.of(grounded("보유·관심 종목의 조회된 변경입니다.", List.of("r1"),
                "ev-issue")), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("hold", "no")));
        var control = new Control(Duration.ofSeconds(60));
        assertEquals("insufficient_evidence", completed(engine().answer(run(), control)).outcome());
        assertEquals(2, control.reserved.size(), "scope and diff once each; no verifier membership requery");
        assertEquals(1, generated.getFirst().branches().size(), "scope stays merged into parent");
        var facts = verifiedFacts.forRequest(verifiedRun, verifiedSections).getFirst();
        assertEquals(2, facts.size());
        var member = assertInstanceOf(ChatModels.PortfolioFact.class, facts.getFirst());
        assertEquals("r1", member.requirementId());
        assertEquals("current_member", member.queryScope());
        assertEquals(List.of(), member.companyIds());
        assertEquals(List.of(new ChatModels.MemberCompany(HYNIX, "SK하이닉스", true, false),
                new ChatModels.MemberCompany(NVDA, "NVIDIA", false, true)), member.companies());
        assertTrue(member.truncated());
        var comparison = assertInstanceOf(ChatModels.ComparisonFact.class, facts.getLast());
        assertEquals("r1", comparison.requirementId());
        assertEquals("v0", comparison.fromVersion());
        assertEquals("v1", comparison.toVersion());
        assertEquals(verifiedRun.context().asOf(), comparison.asOf());
        assertEquals(List.of(HYNIX, NVDA), comparison.targetIds());
        assertEquals(20, comparison.evidenceLimit());
        assertEquals(List.of("added", "removed"), comparison.changes().stream().map(ChatModels.GraphChange::change).toList());
        assertTrue(comparison.truncated());

        ChatRun other = new ChatRun(verifiedRun.jobId(), verifiedRun.sessionId(), "other-member", verifiedRun.attemptNo(),
                verifiedRun.mode(), verifiedRun.turns(), verifiedRun.context(), verifiedRun.selection(),
                verifiedRun.graphVersionId(), verifiedRun.clarificationDepth(), verifiedRun.askedAt(), verifiedRun.deadline());
        assertThrows(ChatModels.Failure.class, () -> verifiedFacts.forRequest(other, verifiedSections));
        assertThrows(ChatModels.Failure.class, () -> verifiedFacts.forRequest(run(), verifiedSections));
        assertThrows(ChatModels.Failure.class, () -> verifiedFacts.forRequest(verifiedRun,
                List.of(grounded("다른 주장", List.of("r1"), "ev-issue"))));
        assertThrows(ChatModels.Failure.class, () -> ChatModels.ServerFacts.capture(other, verifiedSections,
                generated.getFirst().branches()));
        var original = generated.getFirst().branches().getFirst().results().getLast();
        var stale = new ChatToolResult(original.schemaVersion(), original.toolCallId(), original.capabilityId(),
                "v0..stale", original.items(), original.evidenceIds(), original.truncated(), original.nextAllowed(),
                null, original.paths(), original.webResults(), original.provenance());
        var branch = new ChatBranchContext.Branch("r1", "비교", Set.of(ChatQueryType.Q05), false, List.of(stale), false);
        assertThrows(ChatModels.Failure.class, () -> ChatModels.ServerFacts.capture(verifiedRun, verifiedSections,
                List.of(branch)));
        var unbound = new ChatToolResult(original.schemaVersion(), original.toolCallId(), original.capabilityId(),
                original.dataVersion(), original.items(), original.evidenceIds(), original.truncated(), original.nextAllowed(),
                null, original.paths(), original.webResults(), null);
        var unboundBranch = new ChatBranchContext.Branch("r1", "비교", Set.of(ChatQueryType.Q05), false, List.of(unbound), false);
        assertThrows(ChatModels.Failure.class, () -> ChatModels.ServerFacts.capture(verifiedRun, verifiedSections,
                List.of(unboundBranch)));
    }

    // ---- fixtures -------------------------------------------------------------------------------------------------------

    private ChatRouteDecision dependent(String cardinality, int count) {
        return ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1")),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9))
                        .dependingOn(new Dependency("r1", cardinality, count)));
    }

    private OrchestratedChatEngine engine() {
        return engine(null, OrchestratedChatEngine.StageLimits.POLICY);
    }

    private OrchestratedChatEngine engine(ChatModels.Generator replacement, OrchestratedChatEngine.StageLimits limits) {
        List<ChatTool> adapters = tools.entrySet().stream().map(e -> (ChatTool) new ChatTool() {
            public ChatCapability capability() { return e.getKey(); }
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                return e.getValue().apply(scope, request);
            }
        }).toList();
        var registry = new ChatToolRegistry(adapters);
        var runner = new ChatToolRunner(registry);
        runners.add(runner);
        ChatModels.Router router = (run, bound) -> {
            if (routerFailure != null) throw routerFailure;
            return decision;
        };
        ChatModels.Generator generator = (run, context) -> {
            generated.add(context);
            if (generatorFailure != null) throw generatorFailure;
            return answer;
        };
        ChatModels.Verifier verifier = (run, sections, citations, facts) -> {
            verifierCalls++;
            verifiedFacts = facts;
            verifiedRun = run;
            verifiedSections = sections;
            return verdicts;
        };
        ChatCitationSource citations = (id, version, asOf, trace) -> Optional.ofNullable(readable.get(id));
        var engine = new OrchestratedChatEngine(router, replacement != null ? replacement : generator, verifier, registry,
                runner, citations, Clock.fixed(NOW, ZoneOffset.UTC), limits);
        engines.add(engine);
        return engine;
    }

    private static ChatRun run() {
        return ChatPlannerTest.run(0, "v1");
    }

    private static String evidence(String company) {
        return "ev-" + company.toLowerCase().replace(':', '-');
    }

    private static Section general(String text, String requirement) {
        return new Section("general_knowledge", text, List.of(requirement), List.of());
    }

    private static Section grounded(String text, List<String> requirements, String... evidence) {
        return new Section("evidence_grounded", text, requirements, List.of(evidence));
    }

    private static ChatResult completed(ChatEngineOutcome outcome) {
        return assertInstanceOf(ChatEngineOutcome.Completed.class, outcome, outcome.toString()).result();
    }

    private static void assertFailed(String kind, String reason, boolean rerunnable, ChatEngineOutcome outcome) {
        assertEquals(new ChatEngineOutcome.Failed(kind, reason, rerunnable), outcome);
    }

    /** Records what the engine asks of the run. */
    private static final class Control implements ChatRunControl {
        final List<String> phases = new ArrayList<>();
        final List<ChatToolCallReservation> reserved = Collections.synchronizedList(new ArrayList<>());
        final Duration remaining;
        int modelCalls;
        /** Calls earlier attempts of the job made. */
        int spent;

        Control(Duration remaining) {
            this.remaining = remaining;
        }

        @Override public void phase(String phase) { phases.add(phase); }
        @Override public void beforeModelCall() { modelCalls++; }
        @Override public Duration remaining() { return remaining; }
        @Override public boolean owned() { return true; }
        @Override public int toolCallsLeft() { return MAX_TOOL_CALLS - reserved.size() - spent; }
        @Override
        public void shortenDeadline(java.time.Instant deadline) {
            throw new UnsupportedOperationException("only the agent path shortens a deadline");
        }

        @Override
        public List<String> reserveToolCalls(int planRevision, List<ChatToolCallReservation> calls) {
            List<String> ids = new ArrayList<>();
            for (var call : calls) {
                ids.add("tc-" + reserved.size());
                reserved.add(call);
            }
            return ids;
        }

        @Override public void toolCallStarted(String toolCallId) { }

        @Override
        public java.util.Optional<String> claimToolCall(String capabilityId, String inputDigest) {
            throw new UnsupportedOperationException("only the MCP endpoint claims an approved call");
        }
        @Override public void toolCallFinished(String toolCallId, ChatToolCallEnd end) { }
    }
}
