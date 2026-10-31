package com.zoop.chat.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.orchestrator.ChatPeriods;
import com.zoop.chat.orchestrator.ChatPlan;
import com.zoop.chat.orchestrator.ChatPlanner;
import com.zoop.chat.orchestrator.ChatQueryType;
import com.zoop.chat.orchestrator.ChatRouteDecision;
import com.zoop.chat.service.FrozenSelection;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRequest;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.TestFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * D-AI-02: the live spike's questions must be able to take the agent path, or every run of the scenario is refused as direct
 * evidence after its calls were paid for. What the server decides without a model is fixed here: how a question splits, how
 * many companies a requirement names (more than one call's fan-out stays direct), whether it writes a period, and whether
 * the planner takes it at all when the router gives the scenario's capabilities (a plan past the job's calls is asked back).
 */
class ChatLiveSpikeScenariosTest {
    private static final Path SCENARIOS = Path.of("..", "scripts", "chat_live_spike_scenarios.json");
    private static final String GRAPH = "fixture-2026-10-08";
    private static final Instant ASKED = Instant.parse("2026-11-01T03:00:00Z");

    @TestFactory
    Stream<DynamicTest> everyScenarioCanTakeTheAgentPath() throws IOException {
        JsonNode set = JsonMapper.builder().build().readTree(Files.readString(SCENARIOS));
        ChatEvalSetTest.World world = ChatEvalSetTest.world();
        List<DynamicTest> tests = new ArrayList<>();
        set.get("scenarios").properties().forEach(scenario -> tests.add(DynamicTest.dynamicTest(scenario.getKey(), () -> {
            String question = scenario.getValue().get("question").stringValue();
            var pieces = ChatModelStages.effectiveRequirements(question, List.of());
            assertEquals(scenario.getValue().get("requirements").asInt(), pieces.size(), pieces.toString());
            Set<String> tools = new HashSet<>();
            scenario.getValue().get("intendedRounds").forEach(r -> r.forEach(t -> tools.add(t.stringValue())));
            Map<String, Double> capabilities = new HashMap<>();
            for (ChatCapability c : ChatCapability.values()) {
                if (tools.contains(c.id().replace('.', '_')) && !c.web()) capabilities.put(c.id(), 0.9);
            }
            Map<ChatQueryType, Double> types = new EnumMap<>(ChatQueryType.class);
            types.put(ChatQueryType.Q03, 0.9);
            if (capabilities.containsKey("graph.path.read")) types.put(ChatQueryType.Q04, 0.9);
            List<ChatRouteDecision.Requirement> requirements = new ArrayList<>();
            for (var piece : pieces) {
                List<String> named = new ArrayList<>();
                world.names.mentions(piece.text()).forEach(m -> m.companies().forEach(c -> named.add(c.id())));
                assertTrue(named.size() <= ChatToolRequest.MAX_TARGETS, piece.text() + " names " + named.size() + " companies");
                assertTrue(ChatPeriods.parse(piece.text(), ASKED).isEmpty(), piece.text() + " writes a period");
                assertTrue(!named.isEmpty(), piece.text() + " names no company");
                requirements.add(new ChatRouteDecision.Requirement(piece.id(), piece.text(), true, types, capabilities, named, 0.0, null));
            }
            ChatRun run = new ChatRun("job-spike1", "session-1", "member-1", 1, "run",
                    List.of(new ChatRun.Turn("job-spike1", question, null, null)), new ChatFrozenContext(List.of(), 0, null, null, GRAPH),
                    FrozenSelection.NONE, GRAPH, 0, ASKED, ASKED.plusSeconds(60));
            ChatPlan plan = new ChatPlanner().plan(run, new ChatRouteDecision(requirements, null), world.registry().bound());
            assertTrue(plan instanceof ChatPlan.Run, "the planner stops the question: " + plan);
        })));
        return tests.stream();
    }
}
