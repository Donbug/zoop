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
            "chat-router-1", "replay", 10L, 4L, Instant.parse("2026-10-22T01:00:00Z"), Instant.parse("2026-10-22T01:00:01Z"));

    private final List<ChatStageCall> calls = new ArrayList<>();
    private final List<String> recorded = new ArrayList<>();
    private Function<ChatStageCall, ChatStageReply> answer = call -> { throw new AssertionError("no call expected"); };

    private final ChatModelStages stages = stages(new ChatModelRecorder(null, Clock.systemUTC()) {
        @Override
        public String start(String jobId, String stage, String mode) {
            recorded.add("start " + jobId + " " + stage + " " + mode);
            return "aix-1";
        }

        @Override
        public void finish(String id, String status, ChatStageReply.Receipt receipt, String errorCode) {
            recorded.add("finish " + status + " " + (receipt == null ? "-" : receipt.model()) + " " + errorCode);
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
    void theRouterGetsTheSplitRequirementsAndBoundCapabilitiesAndNamesAreResolvedByTheServer() {
        answer = call -> succeeded(call, """
                {"requirements":[
                  {"requirementId":"r1","types":{"Q02":0.9},"capabilities":{},"prohibitedAdvice":0.0},
                  {"requirementId":"r2","types":{"Q03":0.8},"capabilities":{"company.read":0.9,"graph.version.diff":0.8},
                   "prohibitedAdvice":0.05}]}""");
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
        assertEquals(List.of("start chat-job-0001 chat-router replay", "finish succeeded jev null"), recorded);
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
                  "prohibitedAdvice":0.0}]}""");
        ChatRouteDecision picked = stages.route(run(root("한미 관련 공시 알려줘"),
                new ChatRun.Turn("chat-job-0002", "한미사이언스", "c-hanmi-science", "한미사이언스 (008930)")), Set.of("company.read"));
        assertNull(picked.ambiguity());
        assertEquals(List.of("c-hanmi-science"), picked.requirements().getFirst().targets());
        assertEquals("한미사이언스 (008930)", calls.getFirst().input().get("turns").get(1).get("choiceLabel").stringValue());
    }

    @Test
    void aCompanyNamedInAFreeTextReplyResolvesTheSharedNameOfTheQuestion() {
        answer = call -> succeeded(call, """
                {"requirements":[{"requirementId":"r1","types":{"Q03":0.9},"capabilities":{"company.read":0.9},
                  "prohibitedAdvice":0.0}]}""");
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
                {"requirements":[{"requirementId":"r1","types":{"Q02":0.9},"capabilities":{},"prohibitedAdvice":0.0},
                  {"requirementId":"r2","types":{"Q03":0.9},"capabilities":{"company.read":0.9},"prohibitedAdvice":0.0}]}""");
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
        ChatSemanticVerdicts verdicts = stages.verify(run(root("q")), sections, List.of(citation(EV_A, "인용")));
        assertEquals(new ChatSemanticVerdicts.Verdict(null, "no"), verdicts.sections().get(0));
        assertEquals(new ChatSemanticVerdicts.Verdict("supported", "hold"), verdicts.sections().get(1));
        assertEquals("news-provider-1", calls.getFirst().input().get("citations").get(0).get("sourceId").stringValue());
    }

    @Test
    void aZoopDocumentQuoteIsSentUnderTheZoopDocumentGrant() {
        answer = call -> succeeded(call, """
                {"sections":[{"support":"supported","prohibitedAdvice":"no"}]}""");
        var doc = new Citation("zoop_doc", EV_B, "## 2. 보유 기간\n\n탈퇴하면 지웁니다.", null, null, "policy.privacy",
                "2026-10-13.1", 10, 30, "개인정보 처리방침 · 2. 보유 기간", "줍", null, null);
        stages.verify(run(root("q")), List.of(new ChatGeneratedAnswer.Section("zoop_documented", "탈퇴하면 지워집니다.",
                List.of("r1"), List.of(EV_B))), List.of(doc));
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
        var result = new ChatToolResult("chat-tools/v1", "tc-1", "graph.path.read", "gv-1",
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
            public String start(String jobId, String stage, String mode) {
                return "aix-1";
            }

            @Override
            public void finish(String id, String status, ChatStageReply.Receipt receipt, String errorCode) {
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
                {"requirements":[{"requirementId":"r1","types":{"Q02":0.9},"capabilities":{},"prohibitedAdvice":0.0}]}""");
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
