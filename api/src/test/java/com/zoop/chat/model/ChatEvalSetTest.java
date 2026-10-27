package com.zoop.chat.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.stream.Stream;

import com.zoop.ai.chat.ChatStageCall;
import com.zoop.ai.chat.ChatStageReply;
import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatChoice;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatLimitation;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatToolCallReservation;
import com.zoop.chat.model.CompanyNameResolver.Company;
import com.zoop.chat.model.CompanyNameResolver.Entry;
import com.zoop.chat.orchestrator.ChatBranchContext;
import com.zoop.chat.orchestrator.ChatCitationSource;
import com.zoop.chat.orchestrator.ChatEvalProbe;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.orchestrator.ChatRouteDecision;
import com.zoop.chat.orchestrator.OrchestratedChatEngine;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.service.FrozenSelection;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.CompanyReadTool;
import com.zoop.chat.tool.EvidenceResolveTool;
import com.zoop.chat.tool.GraphPathTool;
import com.zoop.chat.tool.IssueReadTool;
import com.zoop.chat.tool.ZoopPolicyReadTool;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.NullNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The fixed chatbot evaluation set (implementation plan stage 7, design summary 10) over replayed model stages. Each question
 * goes through the real requirement splitter, catalog name resolution, planner, read tools on the synthetic public graph
 * fixture, deterministic checks and result building; only the three model stages answer from the case's script. It checks
 * the flow, never answer quality or thresholds. Every case and a summary are written to {@code build/reports/chat-eval/}.
 * Format and fields: docs/development/ai-chatbot-eval-set.md.
 */
class ChatEvalSetTest {
    static final String SET = "chat-eval/chat-eval-v1.json";
    static final String GRAPH = "fixture-2026-10-08";
    static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    static final Path REPORT = Path.of("build", "reports", "chat-eval");
    /** The expectations a case may state; any other key is a typo, not a skipped check. */
    static final Set<String> EXPECTATIONS = Set.of("requirements", "targets", "stages", "tools", "outcome", "reason", "failure",
            "deterministicCheck", "answerBasis", "citationKinds", "limitations", "planned", "droppedGeneral",
            "heldRequirements", "appliedCompanies", "appliedIssues", "graphTargets", "questionOverrodeContext", "choices");
    /** What an {@code evidence_insufficient} limitation's message says for each cause the server names. */
    static final Map<String, String> CAUSE_WORDING = Map.of("evidence_held", "확인하지 못해 뺐어요", "nothing_found",
            "찾지 못했어요");
    private static final Map<String, String> STAGE_NAMES = Map.of(ChatModelStages.ROUTER, "router", ChatModelStages.ANSWER,
            "answer", ChatModelStages.VERIFICATION, "verify");
    private static final ChatStageReply.Receipt RECEIPT = new ChatStageReply.Receipt("replay", "chat-eval", "scripted",
            "chat-eval-v1", "replay", null, null, NOW, NOW);

    private static final List<ObjectNode> reported = Collections.synchronizedList(new ArrayList<>());
    private static JsonNode set;

    @TestFactory
    Stream<DynamicTest> chatEvalV1() {
        set = read(SET);
        World world = new World(set);
        List<DynamicTest> tests = new ArrayList<>();
        for (JsonNode c : set.get("cases")) tests.add(DynamicTest.dynamicTest(c.get("id").stringValue(), () -> run(world, c)));
        return tests.stream();
    }

    @AfterAll
    static void report() throws IOException {
        if (set == null) return;
        Files.createDirectories(REPORT);
        List<ObjectNode> cases = new ArrayList<>(reported);
        cases.sort((a, b) -> a.get("id").stringValue().compareTo(b.get("id").stringValue()));
        ObjectNode report = StrictJson.newObject().put("setVersion", set.get("setVersion").stringValue())
                .put("mode", "replay");
        List<String> ids = new ArrayList<>();
        set.get("cases").forEach(c -> ids.add(c.get("id").stringValue()));
        report.set("summary", summary(ids, cases));
        report.putArray("cases").addAll(cases);
        Files.write(REPORT.resolve("chat-eval-v1.json"), StrictJson.write(report));
        Files.writeString(REPORT.resolve("chat-eval-v1.md"), markdown(report), StandardCharsets.UTF_8);
    }

    @Test
    void aCaseThatThrowsIsReportedAsFailedAndACaseNeverReportedIsNamed() {
        JsonNode first = StrictJson.newObject().put("id", "A01").put("group", "concept").put("question", "질문 1");
        JsonNode second = StrictJson.newObject().put("id", "A02").put("group", "concept").put("question", "질문 2");
        ObjectNode observed = StrictJson.newObject().put("outcome", "answered");
        observed.putArray("tools");
        var passed = entry(first, observed, List.of());
        var thrown = errored(second, List.of("router", "answer"),
                new AssertionError("the script has no answer stage"));
        assertFalse(thrown.get("passed").booleanValue());
        assertEquals("error", thrown.get("observed").get("outcome").stringValue());
        assertTrue(thrown.get("error").stringValue().contains("the script has no answer stage"));

        var summary = summary(List.of("A01", "A02", "A03"), List.of(passed, thrown));
        assertEquals(3, summary.get("setCases").asInt());
        assertEquals(2, summary.get("cases").asInt());
        assertEquals(1, summary.get("passed").asInt());
        assertEquals(1, summary.get("failed").asInt(), "a thrown case is a failure, not a missing row");
        assertEquals(1, summary.get("errors").asInt());
        assertEquals("[\"A03\"]", summary.get("notReported").toString());
    }

    // ---------------------------------------------------------------- one case

    private void run(World world, JsonNode c) {
        String id = c.get("id").stringValue();
        JsonNode script = c.path("script");
        String graph = c.has("graphVersion") ? (c.get("graphVersion").isNull() ? null : c.get("graphVersion").stringValue())
                : GRAPH;
        String job = "chat-eval-" + id;
        ChatRun run = new ChatRun(job, "chat-eval-session", "chat-eval-member", 1, "run",
                List.of(new ChatRun.Turn(job, c.get("question").stringValue(), null, null)),
                new ChatFrozenContext(List.of(), 0, null, null, graph), selection(c.path("selection")), graph, 0, NOW,
                NOW.plusSeconds(60));

        List<String> stages = new ArrayList<>();
        List<ChatRouteDecision> decisions = new ArrayList<>();
        List<String> failedChecks = new ArrayList<>();
        var modelStages = new ChatModelStages(call -> {
            stages.add(STAGE_NAMES.get(call.stage()));
            return reply(call, script);
        }, "replay", world.names, world.issues, world.citations, articleId -> Optional.of("fixture-news"), new ChatModelRecorder(null,
                Clock.systemUTC()) {
            @Override
            public String start(String jobId, String stage, String mode) {
                return "aix-eval";
            }

            @Override
            public void finish(String execution, String status, ChatStageReply.Receipt receipt, String code) {
            }
        });
        ChatModels.Router router = (r, bound) -> {
            ChatRouteDecision decision = modelStages.route(r, bound);
            decisions.add(decision);
            return decision;
        };
        ChatModels.Generator generator = (r, context) -> {
            ChatGeneratedAnswer answer = modelStages.generate(r, context);
            String check = ChatEvalProbe.failedCheck(context.branches(), answer);
            if (check != null) failedChecks.add(check);
            return answer;
        };
        var control = new Control();
        ObjectNode observed;
        List<String> mismatches;
        try {
            ChatEngineOutcome outcome;
            try (var runner = new ChatToolRunner(world.registry);
                    var engine = new OrchestratedChatEngine(router, generator, modelStages, world.registry, runner,
                            world.citations, Clock.fixed(NOW, ZoneOffset.UTC))) {
                outcome = engine.answer(run, control);
            }
            observed = observe(run, outcome, stages, decisions, failedChecks, control);
            mismatches = compare(c.path("expect"), observed);
        } catch (Throwable thrown) {
            // A case that throws (an unscripted stage, a broken observation) is still a failed case of the report.
            reported.add(errored(c, stages, thrown));
            throw thrown;
        }
        reported.add(entry(c, observed, mismatches));
        assertTrue(mismatches.isEmpty(), id + ":\n  " + String.join("\n  ", mismatches));
    }

    static ObjectNode entry(JsonNode c, ObjectNode observed, List<String> mismatches) {
        ObjectNode entry = StrictJson.newObject().put("id", c.get("id").stringValue())
                .put("group", c.get("group").stringValue()).put("question", c.get("question").stringValue())
                .put("passed", mismatches.isEmpty());
        if (c.has("gap")) entry.put("gap", c.get("gap").stringValue());
        entry.set("observed", observed);
        entry.putArray("mismatches").addAll(strings(mismatches));
        return entry;
    }

    /** A case that ended in an exception: failed, with outcome {@code error}, the stages it reached and what was thrown. */
    static ObjectNode errored(JsonNode c, List<String> stages, Throwable thrown) {
        ObjectNode observed = StrictJson.newObject().put("outcome", "error");
        observed.putArray("stages").addAll(strings(stages));
        observed.putArray("tools");
        ObjectNode entry = entry(c, observed, List.of("threw " + thrown));
        entry.put("error", String.valueOf(thrown));
        return entry;
    }

    private static FrozenSelection selection(JsonNode selection) {
        if (selection.isMissingNode()) return FrozenSelection.NONE;
        return new FrozenSelection(list(selection.path("contextIds")), list(selection.path("evidenceIds")),
                list(selection.path("evidencePool")));
    }

    /** The scripted answer of one model stage, with {@code $branch} evidence references read from what the stage was sent. */
    private static ChatStageReply reply(ChatStageCall call, JsonNode script) {
        JsonNode answer;
        switch (call.stage()) {
            case ChatModelStages.ROUTER -> {
                JsonNode routed = script.path("router");
                if (routed.has("fail")) return failure(call, routed.get("fail").stringValue());
                ObjectNode out = StrictJson.newObject();
                ArrayNode requirements = out.putArray("requirements");
                for (JsonNode requirement : call.input().get("requirements")) {
                    String id = requirement.get("requirementId").stringValue();
                    JsonNode r = routed.get(id);
                    if (r == null) throw new AssertionError("the script does not route " + id);
                    requirements.addObject().put("requirementId", id).<ObjectNode>set("types", r.get("types"))
                            .<ObjectNode>set("capabilities", r.get("capabilities"))
                            .put("prohibitedAdvice", r.path("prohibitedAdvice").asDouble(0.0));
                }
                answer = out;
            }
            case ChatModelStages.ANSWER -> {
                JsonNode scripted = script.get("answer");
                if (scripted == null) throw new AssertionError("the script has no answer stage");
                answer = resolved(scripted, call.input());
            }
            default -> {
                JsonNode verify = script.get("verify");
                ObjectNode out = StrictJson.newObject();
                ArrayNode sections = out.putArray("sections");
                if (verify != null) {
                    verify.forEach(sections::add);
                } else {
                    // Unscripted: every section passes, as a verifier that finds nothing wrong would say.
                    for (JsonNode s : call.input().get("sections")) {
                        ObjectNode v = sections.addObject();
                        if ("general_knowledge".equals(s.get("basis").stringValue())) v.putNull("support");
                        else v.put("support", "supported");
                        v.put("prohibitedAdvice", "no");
                    }
                }
                answer = out;
            }
        }
        return new ChatStageReply(call.invocationId(), call.stage(), true, answer, null, RECEIPT);
    }

    private static ChatStageReply failure(ChatStageCall call, String fate) {
        boolean unknown = fate.equals("unknown");
        boolean sent = !fate.equals("refused");
        return new ChatStageReply(call.invocationId(), call.stage(), false, null,
                new ChatStageReply.Failure("scripted_" + fate, sent, unknown), sent ? RECEIPT : null);
    }

    /** {@code $branch} cites every quote its first requirement's branch was sent, {@code $branch:N} the first N of them. */
    private static ObjectNode resolved(JsonNode scripted, JsonNode input) {
        Map<String, List<String>> quoted = new HashMap<>();
        for (JsonNode branch : input.get("branches")) {
            List<String> ids = new ArrayList<>();
            branch.get("evidence").forEach(e -> ids.add(e.get("evidenceId").stringValue()));
            quoted.put(branch.get("requirementId").stringValue(), ids);
        }
        ObjectNode out = StrictJson.newObject();
        ArrayNode sections = out.putArray("sections");
        for (JsonNode s : scripted.path("sections")) {
            ObjectNode section = sections.addObject().put("basis", s.get("basis").stringValue())
                    .put("text", s.get("text").stringValue());
            section.set("requirementIds", s.get("requirementIds"));
            List<String> branch = quoted.getOrDefault(s.get("requirementIds").get(0).stringValue(), List.of());
            ArrayNode evidence = section.putArray("evidenceIds");
            for (JsonNode e : s.get("evidenceIds")) {
                String ref = e.stringValue();
                if (ref.equals("$branch")) branch.forEach(evidence::add);
                else if (ref.startsWith("$branch:")) {
                    branch.stream().limit(Integer.parseInt(ref.substring("$branch:".length()))).forEach(evidence::add);
                } else evidence.add(ref);
            }
        }
        out.set("insufficientRequirementIds", scripted.has("insufficientRequirementIds")
                ? scripted.get("insufficientRequirementIds") : StrictJson.newArray());
        out.set("graphTargetIds", scripted.has("graphTargetIds") ? scripted.get("graphTargetIds") : StrictJson.newArray());
        return out;
    }

    // ---------------------------------------------------------------- what happened

    private static ObjectNode observe(ChatRun run, ChatEngineOutcome outcome, List<String> stages,
            List<ChatRouteDecision> decisions, List<String> failedChecks, Control control) {
        ObjectNode o = StrictJson.newObject();
        o.putArray("requirements").addAll(strings(ChatModelStages.effectiveRequirements(run.turns().getFirst().question(),
                List.of()).stream().map(ChatRequirementSplitter.Piece::text).toList()));
        ObjectNode targets = o.putObject("targets");
        decisions.stream().findFirst().ifPresent(d -> d.requirements()
                .forEach(r -> targets.putArray(r.id()).addAll(strings(r.targets()))));
        o.putArray("stages").addAll(strings(stages));
        o.putArray("tools").addAll(strings(new TreeSet<>(control.capabilities)));
        o.put("deterministicCheck", failedChecks.isEmpty() ? null : failedChecks.getFirst());

        if (outcome instanceof ChatEngineOutcome.Failed failed) {
            o.put("outcome", "failed");
            o.putObject("failure").put("kind", failed.kind()).put("reason", failed.reason())
                    .put("rerunnable", failed.rerunnable());
            return o;
        }
        var completed = (ChatEngineOutcome.Completed) outcome;
        ChatResult result = completed.result();
        JsonNode route = completed.routeSummary();
        // The reason code the server decided; the result carries its wording.
        o.put("outcome", result.outcome()).put("reason", route.path("reason").isString() ? route.get("reason").stringValue() : null)
                .put("reasonText", result.reason()).put("answerBasis", result.answerBasis());
        o.putArray("citationKinds").addAll(strings(new TreeSet<>(result.citations().stream()
                .map(Citation::sourceKind).toList())));
        ArrayNode limitations = o.putArray("limitations");
        for (ChatLimitation l : result.limitations()) {
            limitations.addObject().put("kind", l.kind()).put("label", l.label()).put("message", l.message());
        }
        ArrayNode planned = o.putArray("planned");
        route.path("requirements").forEach(r -> planned.add(r.get("id").stringValue() + ":" + r.get("mode").stringValue()));
        o.putArray("droppedGeneral").addAll(strings(texts(route.path("droppedGeneral"))));
        o.putArray("heldRequirements").addAll(strings(texts(route.path("heldRequirements"))));
        var applied = result.applied();
        o.putArray("appliedCompanies").addAll(strings(applied == null ? List.of()
                : applied.companies().stream().map(ChatAppliedItem::id).toList()));
        o.putArray("appliedIssues").addAll(strings(applied == null ? List.of()
                : applied.issues().stream().map(ChatAppliedItem::id).toList()));
        o.put("questionOverrodeContext", applied != null && applied.questionOverrodeContext());
        o.putArray("graphTargets").addAll(strings(result.graphTargets().stream().map(GraphTarget::id).toList()));
        o.putArray("choices").addAll(strings(result.choices() == null ? List.<String>of()
                : result.choices().stream().map(ChatChoice::id).toList()));
        return o;
    }

    /** Every stated expectation that the run did not meet, in words. */
    private static List<String> compare(JsonNode expect, ObjectNode observed) {
        List<String> mismatches = new ArrayList<>();
        for (var entry : expect.properties()) {
            String key = entry.getKey();
            JsonNode want = entry.getValue();
            if (!EXPECTATIONS.contains(key)) {
                mismatches.add("unknown expectation " + key);
                continue;
            }
            JsonNode got = observed.get(key);
            if (key.equals("limitations")) {
                if (!limitationsMatch(want, got)) mismatches.add("limitations: expected " + want + " but was " + got);
            } else if (key.equals("targets")) {
                want.properties().forEach(t -> {
                    if (!t.getValue().equals(got.path(t.getKey()))) {
                        mismatches.add("targets." + t.getKey() + ": expected " + t.getValue() + " but was " + got.path(t.getKey()));
                    }
                });
            } else if (!want.equals(got == null ? NullNode.getInstance() : got)) {
                mismatches.add(key + ": expected " + want + " but was " + got);
            }
        }
        return mismatches;
    }

    /** Kind and label in order; a {@code cause} must show in the message the server wrote. */
    private static boolean limitationsMatch(JsonNode want, JsonNode got) {
        if (got == null || want.size() != got.size()) return false;
        for (int i = 0; i < want.size(); i++) {
            JsonNode w = want.get(i);
            JsonNode g = got.get(i);
            if (!w.get("kind").equals(g.get("kind"))) return false;
            if (w.has("label") && !w.get("label").equals(g.get("label"))) return false;
            if (w.has("cause")) {
                String wording = CAUSE_WORDING.get(w.get("cause").stringValue());
                if (wording == null || g.get("message").isNull() || !g.get("message").stringValue().contains(wording)) {
                    return false;
                }
            }
        }
        return true;
    }

    // ---------------------------------------------------------------- report

    /**
     * Counts by outcome and group, and the two rates the set is meant to follow once real data and models run it: how often
     * a question that read data ends without evidence, and how often a concept part the server split off is dropped. On the
     * replay they only show that the counting works.
     */
    /**
     * The counts over the reported cases, checked against the set: {@code setCases} is every case of the set and
     * {@code notReported} the ids no run reported (a filtered run, or a case that never started), so a missing case is never
     * read as passed.
     */
    static ObjectNode summary(List<String> setIds, List<ObjectNode> cases) {
        ObjectNode summary = StrictJson.newObject();
        long passed = cases.stream().filter(c -> c.get("passed").booleanValue()).count();
        Set<String> seen = new TreeSet<>();
        cases.forEach(c -> seen.add(c.get("id").stringValue()));
        summary.put("setCases", setIds.size()).put("cases", cases.size()).put("passed", passed)
                .put("failed", cases.size() - passed).put("errors", cases.stream().filter(c -> c.has("error")).count());
        summary.putArray("notReported").addAll(strings(setIds.stream().filter(id -> !seen.contains(id)).toList()));
        Map<String, Integer> outcomes = new TreeMap<>();
        Map<String, Integer> groups = new TreeMap<>();
        int read = 0;
        int insufficient = 0;
        int concepts = 0;
        int dropped = 0;
        for (ObjectNode c : cases) {
            JsonNode o = c.get("observed");
            outcomes.merge(o.get("outcome").stringValue(), 1, Integer::sum);
            groups.merge(c.get("group").stringValue(), 1, Integer::sum);
            if (!o.get("tools").isEmpty()) {
                read++;
                boolean short_ = "insufficient_evidence".equals(o.get("outcome").stringValue());
                for (JsonNode l : o.path("limitations")) short_ |= "evidence_insufficient".equals(l.get("kind").stringValue());
                if (short_) insufficient++;
            }
            boolean concept = false;
            for (JsonNode p : o.path("planned")) concept |= p.stringValue().contains("-c:");
            if (concept) {
                concepts++;
                if (!o.path("droppedGeneral").isEmpty()) dropped++;
            }
        }
        ObjectNode byOutcome = summary.putObject("outcomes");
        outcomes.forEach(byOutcome::put);
        ObjectNode byGroup = summary.putObject("groups");
        groups.forEach(byGroup::put);
        summary.putObject("insufficientEvidence").put("casesThatRead", read).put("withoutEvidence", insufficient);
        summary.putObject("droppedGeneral").put("casesWithConcept", concepts).put("dropped", dropped);
        summary.put("gaps", cases.stream().filter(c -> c.has("gap")).count());
        return summary;
    }

    private static String markdown(ObjectNode report) {
        JsonNode s = report.get("summary");
        StringBuilder md = new StringBuilder("# 챗봇 평가 결과 (").append(report.get("setVersion").stringValue())
                .append(", ").append(report.get("mode").stringValue()).append(")\n\n");
        md.append("대본 응답(replay)은 흐름 회귀만 확인한다. 아래 비율은 집계가 동작하는지 보이는 값이며 품질 지표가 아니다.\n\n");
        md.append("- 세트 ").append(s.get("setCases").asInt()).append("건 중 보고 ").append(s.get("cases").asInt())
                .append("건, 통과 ").append(s.get("passed").asInt()).append("건, 실패 ").append(s.get("failed").asInt())
                .append("건(예외 ").append(s.get("errors").asInt()).append("건 포함)\n");
        if (!s.get("notReported").isEmpty()) {
            List<String> missing = new ArrayList<>();
            s.get("notReported").forEach(n -> missing.add(n.stringValue()));
            md.append("- **보고되지 않은 사례 ").append(missing.size()).append("건**: ").append(String.join(", ", missing))
                    .append(" (통과로 세지 않는다)\n");
        }
        md.append("- 결과 분포: ").append(s.get("outcomes")).append('\n');
        JsonNode ins = s.get("insufficientEvidence");
        md.append("- 근거 부족: 조회한 사례 ").append(ins.get("casesThatRead").asInt()).append("건 중 ")
                .append(ins.get("withoutEvidence").asInt()).append("건\n");
        JsonNode drop = s.get("droppedGeneral");
        md.append("- 개념 하위 요구 제외(droppedGeneral): 개념 하위 요구가 있던 사례 ").append(drop.get("casesWithConcept").asInt())
                .append("건 중 ").append(drop.get("dropped").asInt()).append("건\n\n");
        md.append("| 사례 | 유형 | 결과 | 통과 | 알려진 공백 |\n| --- | --- | --- | --- | --- |\n");
        for (JsonNode c : report.get("cases")) {
            JsonNode o = c.get("observed");
            String result = o.get("outcome").stringValue() + (o.path("reason").isString() ? " / " + o.get("reason").stringValue()
                    : o.has("failure") ? " / " + o.get("failure").get("kind").stringValue() : "");
            md.append("| ").append(c.get("id").stringValue()).append(" | ").append(c.get("group").stringValue()).append(" | ")
                    .append(result).append(" | ").append(c.get("passed").booleanValue() ? "예" : "아니오").append(" | ")
                    .append(c.has("gap") ? c.get("gap").stringValue().replace("|", "\\|") : "").append(" |\n");
        }
        return md.toString();
    }

    // ---------------------------------------------------------------- the synthetic world

    /**
     * What the tools read: the public graph fixture pinned at {@link #GRAPH}, the case set's catalog names and profiles, two
     * ZOOP policies and a citation for every evidence of these. Every evidence is readable.
     */
    static final class World {
        final CompanyNameResolver names;
        final IssueNameResolver issues;
        final ChatCitationSource citations;
        final ChatToolRegistry registry;

        World(JsonNode set) {
            List<Entry> catalog = new ArrayList<>();
            Map<String, String> companyNames = new HashMap<>();
            for (JsonNode c : set.get("catalog")) {
                var company = new Company(c.get("id").stringValue(), c.get("name").stringValue(), c.get("ticker").stringValue());
                companyNames.put(company.id(), company.name());
                catalog.add(new Entry(company.name().toLowerCase(java.util.Locale.ROOT), company));
                c.get("aliases").forEach(a -> catalog.add(new Entry(a.stringValue().toLowerCase(java.util.Locale.ROOT), company)));
            }
            names = new CompanyNameResolver(null) {
                @Override
                public List<Mention> mentions(String text) {
                    return match(text, catalog);
                }
            };

            Map<String, Citation> byId = new LinkedHashMap<>();
            JsonNode fixture = read("graph-fixtures/" + GRAPH + ".json");
            Map<String, JsonNode> articles = new HashMap<>();
            fixture.get("articles").forEach(a -> articles.put(a.get("articleId").stringValue(), a));
            for (JsonNode e : fixture.get("evidence")) {
                JsonNode article = articles.get(e.get("articleId").stringValue());
                String title = article.get("title").stringValue();
                String quote = title + " 본문 인용";
                byId.put(e.get("evidenceId").stringValue(), new Citation("article", e.get("evidenceId").stringValue(), quote,
                        article.get("articleId").stringValue(), article.get("version").stringValue(), null, null, 0,
                        quote.length(), title, "합성 언론사", published(article.get("publishedAt").stringValue()),
                        article.get("url").stringValue()));
            }

            Map<String, ChatCompanyProfiles.Quote> profiles = new HashMap<>();
            set.get("profiles").properties().forEach(p -> {
                String name = companyNames.get(p.getKey());
                String text = name + "(" + p.getKey() + ") 사업 개요: " + p.getValue().stringValue();
                var quote = new ChatCompanyProfiles.Quote(evidenceId("company_profile\n" + p.getKey() + "\n" + text), p.getKey(),
                        name, text, null, Instant.parse("2026-10-01T00:00:00Z"));
                profiles.put(p.getKey(), quote);
                byId.put(quote.evidenceId(), new Citation("company_profile", quote.evidenceId(), text, null, null, p.getKey(),
                        null, 0, text.length(), quote.title(), ChatCompanyProfiles.PUBLISHER, null, null));
            });

            Map<String, ChatZoopDocs.Document> policies = new HashMap<>();
            policy(policies, byId, "policy.service", "서비스 이용약관", "이용 제한", "회원이 약관을 어기면 서비스 이용을 제한할 수 있습니다.",
                    "탈퇴", "회원은 언제든지 탈퇴할 수 있습니다.");
            policy(policies, byId, "policy.privacy", "개인정보 처리방침", "보관 기간",
                    "회원 탈퇴 시 질문 기록은 30일 동안 보관한 뒤 지웁니다.", "제3자 제공", "법령이 정한 경우 외에는 제3자에게 제공하지 않습니다.");

            citations = (evidenceId, graphVersion, asOf, traceId) -> Optional.ofNullable(byId.get(evidenceId));
            PublicGraphReader reader = reader();
            issues = new IssueNameResolver(reader);
            ChatEvidenceAccess access = (evidenceId, graphVersion, asOf, requestId) -> true;
            var companyProfiles = new ChatCompanyProfiles(null, null, reader) {
                @Override
                public Optional<Quote> forCompany(String companyId) {
                    return Optional.ofNullable(profiles.get(companyId));
                }
            };
            var docs = new ChatZoopDocs(null, Clock.fixed(NOW, ZoneOffset.UTC)) {
                @Override
                public Optional<Document> inEffect(String docId, Instant asOf) {
                    return Optional.ofNullable(policies.get(docId));
                }
            };
            registry = new ChatToolRegistry(List.of(new CompanyReadTool(reader, access, companyProfiles),
                    new IssueReadTool(reader, access), new EvidenceResolveTool(reader, access),
                    new GraphPathTool(reader, access), new ZoopPolicyReadTool(docs)));
        }

        private static void policy(Map<String, ChatZoopDocs.Document> policies, Map<String, Citation> citations, String docId,
                String title, String... headedTexts) {
            List<ChatZoopDocs.Quote> quotes = new ArrayList<>();
            for (int i = 0; i < headedTexts.length; i += 2) {
                String text = headedTexts[i + 1];
                var quote = new ChatZoopDocs.Quote(evidenceId("zoop_doc\n" + docId + "\n" + text), docId, "2026-10-01",
                        title + " · " + headedTexts[i], text, 0, text.length());
                quotes.add(quote);
                citations.put(quote.evidenceId(), new Citation("zoop_doc", quote.evidenceId(), text, null, null, docId,
                        "2026-10-01", 0, text.length(), quote.title(), "줍", null, null));
            }
            policies.put(docId, new ChatZoopDocs.Document(docId, "2026-10-01", title, quotes));
        }

        /** Only {@link #GRAPH} exists, active since 2026-10-08; any other version cannot be read. */
        private static PublicGraphReader reader() {
            var record = new GraphVersionRecord(GRAPH, 1, "fixture", "artifact-" + GRAPH,
                    FixtureGraphSnapshotStore.URI_PREFIX + GRAPH + ".json",
                    FixtureGraphSnapshotStore.sha256(bytes("graph-fixtures/" + GRAPH + ".json")), true);
            GraphVersionRepository versions = new GraphVersionRepository() {
                public Optional<GraphVersionRecord> find(String id) { return Optional.of(record).filter(r -> r.id().equals(id)); }
                public Optional<GraphVersionRecord> active() { return Optional.of(record); }
                public Optional<String> activeVersionIdAt(Instant asOf) { return Optional.of(GRAPH); }
                public boolean everActivated(String id) { return GRAPH.equals(id); }
            };
            return new PublicGraphReader(new GraphVersionSelector(versions, Clock.fixed(NOW, ZoneOffset.UTC)),
                    new FixtureGraphSnapshotStore(ChatEvalSetTest.class.getClassLoader()), pinned -> DisclosureExclusions.NONE);
        }
    }

    /** Records the model calls and tool calls the engine announces; the run never runs out of time. */
    private static final class Control implements ChatRunControl {
        final List<String> capabilities = Collections.synchronizedList(new ArrayList<>());
        private int reserved;

        @Override public void phase(String phase) { }
        @Override public void beforeModelCall() { }
        @Override public Duration remaining() { return Duration.ofSeconds(60); }
        @Override public boolean owned() { return true; }

        @Override
        public List<String> reserveToolCalls(int planRevision, List<ChatToolCallReservation> calls) {
            List<String> ids = new ArrayList<>();
            for (var call : calls) {
                capabilities.add(call.capabilityId());
                ids.add("tc-" + reserved++);
            }
            return ids;
        }

        @Override public void toolCallStarted(String toolCallId) { }
        @Override public void toolCallFinished(String toolCallId, ChatToolCallEnd end) { }
    }

    // ---------------------------------------------------------------- helpers

    static JsonNode read(String resource) {
        return StrictJson.parseObject(bytes(resource)).node();
    }

    private static byte[] bytes(String resource) {
        try (InputStream in = ChatEvalSetTest.class.getClassLoader().getResourceAsStream(resource)) {
            if (in == null) fail("missing resource " + resource);
            return in.readAllBytes();
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** A fixture date without a time is that day at midnight UTC. */
    private static Instant published(String value) {
        return Instant.parse(value.length() == 10 ? value + "T00:00:00Z" : value);
    }

    private static String evidenceId(String text) {
        try {
            return "ev-" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(text.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static List<String> list(JsonNode array) {
        List<String> values = new ArrayList<>();
        array.forEach(v -> values.add(v.stringValue()));
        return values;
    }

    private static List<String> texts(JsonNode array) {
        return list(array);
    }

    private static ArrayNode strings(Iterable<String> values) {
        ArrayNode array = StrictJson.newArray();
        values.forEach(array::add);
        return array;
    }
}
