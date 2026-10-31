package com.zoop.chat.orchestrator;

import com.zoop.chat.orchestrator.ChatPlan.Planned;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.common.json.StrictJson;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.node.ArrayNode;

/**
 * Where each requirement of a run ended, as the server decided it (implementation plan 4, {@code ChatRequirementCoverage}):
 * every requirement the member stated and every one the plan took starts {@code PENDING} and ends answered, limited or asked
 * back, with the calls that served it and the machine code of why it was not answered. A model's own view of coverage is no
 * input here. An answer leaving anything pending is not delivered; the record goes to the route summary, never to the member.
 * A member-scope source is no requirement of its own: its calls count for the requirement it serves.
 */
final class ChatRequirementCoverage {
    enum Status { PENDING, ANSWERED, LIMITED, CLARIFY }

    record Entry(String requirementId, boolean explicit, Status status, List<String> toolCallIds, String reason) {
        Entry {
            toolCallIds = List.copyOf(toolCallIds);
        }

        private Entry decided(Status next, String why) {
            return new Entry(requirementId, explicit, next, toolCallIds, why);
        }
    }

    private final Map<String, Entry> entries = new LinkedHashMap<>();

    ChatRequirementCoverage(ChatRouteDecision decision) {
        decision.requirements().stream().filter(ChatRouteDecision.Requirement::explicit)
                .forEach(r -> entries.put(r.id(), new Entry(r.id(), true, Status.PENDING, List.of(), null)));
    }

    /** Adds what the plan took beyond the stated requirements: inferred ones and split-off concepts. */
    void plan(ChatPlan.Run plan) {
        plan.requirements().stream().filter(p -> p.origin() != ChatPlan.Origin.SCOPE)
                .forEach(p -> entries.putIfAbsent(p.id(), new Entry(p.id(), false, Status.PENDING, List.of(), null)));
    }

    /** Records the calls behind each requirement, with those of the member-scope source it reads on. */
    void read(ChatPlan.Run plan, Map<String, List<ChatToolResult>> results) {
        for (Planned p : plan.requirements()) {
            if (!entries.containsKey(p.id())) continue;
            Set<String> calls = new LinkedHashSet<>();
            if (p.onScope()) results.getOrDefault(p.dependsOn().requirementId(), List.of()).forEach(r -> calls.add(r.toolCallId()));
            results.getOrDefault(p.id(), List.of()).forEach(r -> calls.add(r.toolCallId()));
            calls.remove(null);
            entries.computeIfPresent(p.id(), (id, e) -> new Entry(id, e.explicit(), e.status(), List.copyOf(calls), e.reason()));
        }
    }

    void answered(String id) {
        entries.computeIfPresent(id, (key, e) -> e.decided(Status.ANSWERED, null));
    }

    void limited(String id, String reason) {
        entries.computeIfPresent(id, (key, e) -> e.decided(Status.LIMITED, reason));
    }

    /** The run ended without an answer: what is still pending ends with it, what was decided keeps its own reason. */
    void end(Status status, String reason) {
        entries.replaceAll((id, e) -> e.status() == Status.PENDING ? e.decided(status, reason) : e);
    }

    /** The run ended on a server stop: asked back, or guidance that limits what was left. */
    void stopped(ChatPlan.Stop stop) {
        end("clarification".equals(stop.outcome()) ? Status.CLARIFY : Status.LIMITED, stop.reason());
    }

    /** Whether every requirement reached an end. */
    boolean settled() {
        return entries.values().stream().noneMatch(e -> e.status() == Status.PENDING);
    }

    List<Entry> entries() {
        return List.copyOf(entries.values());
    }

    /** The route summary's record: ids and machine codes only. */
    ArrayNode json() {
        ArrayNode array = StrictJson.newArray();
        for (Entry e : entries.values()) {
            var node = array.addObject().put("requirementId", e.requirementId()).put("explicit", e.explicit())
                    .put("status", e.status().name().toLowerCase());
            var calls = node.putArray("toolCallIds");
            e.toolCallIds().forEach(calls::add);
            if (e.reason() != null) node.put("reason", e.reason());
        }
        return array;
    }
}
