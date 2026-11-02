package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.MemoryChatStore;
import com.zoop.chat.executor.NoChatTransactions;
import com.zoop.chat.model.ChatEvalSetTest;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.orchestrator.ChatQueryType;
import com.zoop.chat.orchestrator.ChatRouteDecision;
import com.zoop.chat.orchestrator.ChatSemanticVerdicts;
import com.zoop.chat.orchestrator.OrchestratedChatEngine;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolRunners;
import com.zoop.chat.tool.ChatWebSearchTool;
import com.zoop.chat.tool.SyntheticWebSearchProvider;
import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.spec.McpSchema;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.stream.Stream;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.TestFactory;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * The fixed evaluation of the agent path: the real engine, approval gate, MCP tools, ledger, send gate and synthetic web
 * provider over the evaluation set's graph; only Luna answers from the case's script. It fixes what the server approves and
 * what becomes of the answer, never answer quality. Requirements are written in the case: splitting and routing are the direct
 * set's. Format: docs/development/ai-chatbot-eval-set.md.
 */
class ChatAgentEvalTest {
    private static final String SET = "chat-eval/chat-eval-agent-v1.json";
    private static final Set<String> EXPECTATIONS = Set.of("path", "decisions", "tools", "outcome", "failure", "answerBasis",
            "answerStatus", "citationKinds", "limitations", "notices", "coverage", "uiActions");
    private static final Instant NOW = ChatMcpGrantsTest.NOW;
    private static final String GRAPH = "fixture-2026-10-08";
    private static final String SELECTION = "{\"contextIds\":[],\"evidenceIds\":[],\"evidencePool\":[]}";

    private final JsonMapper mapper = JsonMapper.builder().build();
    private final Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);

    /** Luna behind the provider: makes the approved calls of the last step, then answers from the case's next step. */
    private final class Luna implements ChatModels.Agent {
        private final JsonNode steps;
        private final ChatMcpTools tools;
        private final ChatMcpGrants grants;
        private final Map<String, ChatModels.ApprovalRequest> asked = new HashMap<>();
        private final Map<String, Set<String>> read = new HashMap<>();
        private final Map<String, Set<String>> hits = new HashMap<>();
        final List<String> decisions = new ArrayList<>();

        Luna(JsonNode steps, ChatMcpTools tools, ChatMcpGrants grants) {
            this.steps = steps;
            this.tools = tools;
            this.grants = grants;
        }

        @Override
        public ChatModels.AgentStep step(com.zoop.chat.executor.ChatRun run, int step, ChatModels.AgentInput input) {
            var grant = grants.verify(input.grantToken()).orElseThrow();
            var context = McpTransportContext.create(Map.of(ChatMcpTools.GRANT, grant));
            for (ChatModels.Decision decision : input.decisions()) {
                decisions.add(decision.approvalRequestId() + ":" + (decision.approve() ? "approved" : "denied"));
                if (decision.approve()) make(context, asked.get(decision.approvalRequestId()));
            }
            if (step > steps.size()) throw new AssertionError("the script has no step " + step);
            JsonNode scripted = steps.get(step - 1);
            if (scripted.has("answer")) {
                return new ChatModels.AgentStep("resp_" + step, List.of(), answer(scripted.get("answer")));
            }
            List<ChatModels.ApprovalRequest> calls = new ArrayList<>();
            scripted.get("calls").forEach(c -> {
                Map<String, Object> arguments = new LinkedHashMap<>();
                if (c.has("targets")) arguments.put("targets", strings(c.get("targets")));
                var request = new ChatModels.ApprovalRequest(c.get("id").stringValue(), c.get("tool").stringValue(), arguments,
                        strings(c.path("requirementIds")));
                asked.put(request.id(), request);
                calls.add(request);
            });
            return new ChatModels.AgentStep("resp_" + step, calls, null);
        }

        private void make(McpTransportContext context, ChatModels.ApprovalRequest request) {
            Map<String, Object> called = new HashMap<>(request.arguments());
            called.put(ChatMcpTools.REQUIREMENT_IDS, request.requirementIds());
            var result = tools.call(context, new McpSchema.CallToolRequest(request.toolName(), called));
            if (Boolean.TRUE.equals(result.isError())) return;
            JsonNode content = mapper.valueToTree(result.structuredContent());
            for (String requirement : request.requirementIds()) {
                content.path("evidenceIds").forEach(e -> read.computeIfAbsent(requirement, r -> new LinkedHashSet<>())
                        .add(e.stringValue()));
                content.path("webResults").forEach(h -> hits.computeIfAbsent(requirement, r -> new LinkedHashSet<>())
                        .add(h.get("id").stringValue()));
            }
        }

        /** {@code $reads} cites what the section's first requirement read, {@code $web} what its searches found. */
        private ChatGeneratedAnswer answer(JsonNode scripted) {
            List<ChatGeneratedAnswer.Section> sections = new ArrayList<>();
            for (JsonNode s : scripted.path("sections")) {
                List<String> requirements = strings(s.get("requirementIds"));
                List<String> evidence = new ArrayList<>();
                for (String ref : strings(s.path("evidenceIds"))) {
                    String owner = requirements.getFirst();
                    if (ref.equals("$reads")) evidence.addAll(read.getOrDefault(owner, Set.of()));
                    else if (ref.equals("$web")) evidence.addAll(hits.getOrDefault(owner, Set.of()));
                    else evidence.add(ref.equals("$reads:r2") ? read.getOrDefault("r2", Set.of()).iterator().next() : ref);
                }
                sections.add(new ChatGeneratedAnswer.Section(s.get("basis").stringValue(), s.get("text").stringValue(),
                        requirements, evidence));
            }
            return new ChatGeneratedAnswer(sections, strings(scripted.path("insufficientRequirementIds")),
                    strings(scripted.path("graphTargetIds")));
        }
    }

    private static List<String> strings(JsonNode values) {
        List<String> out = new ArrayList<>();
        values.forEach(v -> out.add(v.stringValue()));
        return out;
    }

    @TestFactory
    Stream<DynamicTest> chatEvalAgentV1() throws IOException {
        JsonNode set;
        try (InputStream in = getClass().getClassLoader().getResourceAsStream(SET)) {
            assertNotNull(in, SET);
            set = mapper.readTree(in);
        }
        ChatEvalSetTest.World world = ChatEvalSetTest.world();
        List<DynamicTest> tests = new ArrayList<>();
        int[] job = {0};
        set.get("cases").forEach(c -> tests.add(DynamicTest.dynamicTest(c.get("id").stringValue(),
                () -> run(world, c, "job-a" + String.format("%04d", ++job[0])))));
        return tests.stream();
    }

    private void run(ChatEvalSetTest.World world, JsonNode c, String job) {
        world.unavailable(Set.copyOf(strings(c.path("unavailableTools"))));
        MemoryChatStore store = new MemoryChatStore();
        running(store, job, c.get("question").stringValue());
        ChatToolRegistry registry = world.registryWith(new ChatWebSearchTool(new SyntheticWebSearchProvider(), clock));
        Path dir;
        try {
            dir = Files.createTempDirectory("chat-agent-eval");
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        Path grantsFile = ChatSendGrantsTest.write(dir.resolve("grants.json"), ChatCompanyProfiles.SOURCE_ID, ChatZoopDocs.SOURCE_ID,
                ChatMcpSendGate.GRAPH_SOURCE_ID, ChatSendGrantsTest.EVIDENCE_SOURCE, ChatMcpSendGate.webSource("synthetic"));
        var gate = new ChatMcpSendGate(new ChatSendGrants(grantsFile.toString(), ChatSendGrantsTest.RECIPIENT, clock), (r, ids) -> {
            Map<String, String> placed = new LinkedHashMap<>();
            ids.forEach(id -> placed.put(id, ChatSendGrantsTest.EVIDENCE_SOURCE));
            return placed;
        });
        var executor = new ChatJobExecutor(store, store,
                new StaticListableBeanFactory(Map.of()).getBeanProvider(ChatEngine.class), mapper, clock, new NoChatTransactions());
        var grants = ChatMcpGrantsTest.grants("k1", "k1=" + ChatMcpGrantsTest.KEY_A, NOW);
        try (ChatToolRunner runner = ChatToolRunners.withAmpleTime(registry)) {
            var tools = new ChatMcpTools(registry, runner, executor, gate, mapper);
            var luna = new Luna(c.path("agent"), tools, grants);
            var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, null);
            ChatRouteDecision decision = decision(c.get("requirements"));
            ChatModels.Router router = (r, bound) -> decision;
            ChatModels.Generator generator = (r, context) -> {
                throw new AssertionError("the run left the agent path");
            };
            ChatModels.Verifier verifier = (r, sections, citations, facts) -> new ChatSemanticVerdicts(sections.stream()
                    .map(s -> new ChatSemanticVerdicts.Verdict("general_knowledge".equals(s.basis()) ? null : "supported", "no"))
                    .toList());
            try (var engine = new OrchestratedChatEngine(router, generator, verifier, registry, runner, world.citations(), clock,
                    agent)) {
                var attached = executor.attach(job, 1).orElseThrow();
                ChatEngineOutcome outcome = engine.answer(attached.run(), attached.control());
                compare(c, observe(outcome, luna, store.toolCalls(job).stream().map(t -> t.row.capabilityId()).toList()));
            }
        } finally {
            world.unavailable(Set.of());
        }
    }

    private static void running(MemoryChatStore store, String job, String question) {
        String attempts = "[{\"n\":1,\"mode\":\"run\",\"requestKey\":\"" + job + "\",\"status\":\"running\","
                + "\"ownerToken\":\"owner-1\"}]";
        String context = "{\"items\":[],\"evidenceCount\":0,\"period\":null,\"asOf\":null,\"graphVersion\":\"" + GRAPH + "\"}";
        store.add(new ChatJobRow(job, "conv-" + job, "member-a", 1, question, "a".repeat(64), NOW, context, SELECTION, List.of(),
                GRAPH, "queued", null, null, null, null, 0, null, null, 0, attempts, NOW, NOW, null));
        assertTrue(store.start(job, "owner-1", NOW.plusSeconds(60), NOW.plusSeconds(60), attempts, NOW));
    }

    private static ChatRouteDecision decision(JsonNode requirements) {
        List<ChatRouteDecision.Requirement> out = new ArrayList<>();
        for (JsonNode r : requirements) {
            Map<ChatQueryType, Double> types = new EnumMap<>(ChatQueryType.class);
            r.get("types").properties().forEach(t -> types.put(ChatQueryType.valueOf(t.getKey()), t.getValue().asDouble()));
            Map<String, Double> capabilities = new HashMap<>();
            r.path("capabilities").properties().forEach(t -> capabilities.put(t.getKey(), t.getValue().asDouble()));
            out.add(new ChatRouteDecision.Requirement(r.get("id").stringValue(), r.get("label").stringValue(), true, types,
                    capabilities, strings(r.path("targets")), 0.0, null));
        }
        return new ChatRouteDecision(out, null);
    }

    private Map<String, Object> observe(ChatEngineOutcome outcome, Luna luna, List<String> tools) {
        Map<String, Object> o = new LinkedHashMap<>();
        o.put("decisions", luna.decisions);
        o.put("tools", new ArrayList<>(new TreeSet<>(tools)));
        if (outcome instanceof ChatEngineOutcome.Failed failed) {
            o.put("outcome", "failed");
            Map<String, Object> failure = new LinkedHashMap<>();
            failure.put("kind", failed.kind());
            failure.put("reason", failed.reason());
            failure.put("rerunnable", failed.rerunnable());
            o.put("failure", failure);
            return o;
        }
        var completed = (ChatEngineOutcome.Completed) outcome;
        ChatResult result = completed.result();
        JsonNode route = completed.routeSummary();
        route.path("coverage").forEach(entry -> assertTrue(!"pending".equals(entry.path("status").asString()), entry.toString()));
        List<String> coverage = new ArrayList<>();
        route.path("coverage").forEach(e -> coverage.add(e.get("requirementId").stringValue() + ":" + e.get("status").stringValue()));
        o.put("path", route.path("path").asString(null));
        o.put("outcome", result.outcome());
        o.put("answerBasis", result.answerBasis());
        o.put("answerStatus", result.answerStatus());
        o.put("citationKinds", new ArrayList<>(new TreeSet<>(result.citations().stream().map(Citation::sourceKind).toList())));
        o.put("limitations", result.limitations().stream().map(l -> l.kind()).toList());
        o.put("notices", result.notices().stream().map(n -> n.code()).toList());
        o.put("coverage", coverage);
        o.put("uiActions", result.uiActions().stream().map(a -> a.kind()).toList());
        return o;
    }

    private void compare(JsonNode c, Map<String, Object> observed) {
        List<String> mismatches = new ArrayList<>();
        JsonNode got = mapper.valueToTree(observed);
        for (var entry : c.get("expect").properties()) {
            if (!EXPECTATIONS.contains(entry.getKey())) mismatches.add("unknown expectation " + entry.getKey());
            else if (!entry.getValue().equals(got.path(entry.getKey()))) {
                mismatches.add(entry.getKey() + ": expected " + entry.getValue() + " but was " + got.path(entry.getKey()));
            }
        }
        assertTrue(mismatches.isEmpty(), c.get("id").stringValue() + ":\n  " + String.join("\n  ", mismatches) + "\n  observed " + got);
    }
}
