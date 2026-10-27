package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.ChatChoice;
import com.zoop.chat.tool.ChatCapability;
import java.util.List;
import java.util.Set;

/** What the planner decided: either a stop before any tool call, or the requirements and how each is served. */
public sealed interface ChatPlan {
    /**
     * Ends the job before any tool call: {@code clarification} (with choices, or none for free input) or {@code guidance}.
     * {@code reason} is a machine code the result turns into a server sentence.
     */
    record Stop(String outcome, String reason, List<ChatChoice> choices) implements ChatPlan {
        public Stop {
            choices = choices == null ? List.of() : List.copyOf(choices);
        }
    }

    /** The confirmed plan, requirements in route order. */
    record Run(List<Planned> requirements) implements ChatPlan {
        public Run {
            requirements = List.copyOf(requirements);
        }

        public int stages() {
            return requirements.stream().mapToInt(Planned::stage).max().orElse(0);
        }
    }

    /** How a requirement is served: a Q02 general section, tool reads, or a server limitation (never a model's choice). */
    enum Mode { GENERAL, TOOLS, LIMITED }

    /**
     * Where a TOOLS requirement's targets came from. {@code SERVER}: it reads only ZOOP documents, whose targets are fixed
     * ({@link com.zoop.chat.tool.ChatCapability#documents()}).
     */
    enum TargetSource { QUESTION, CONTEXT, DEPENDENCY, SERVER }

    /**
     * Who asked for a requirement. {@code ROUTER}: the route decision. {@code CONCEPT}: the server split the Q02 part off a
     * router requirement that also asks for a fact (partial-answer design, part 1). The member never stated it as such, so
     * leaving it unanswered is no limitation.
     */
    enum Origin { ROUTER, CONCEPT }

    /**
     * One planned requirement. TOOLS requirements read {@code capabilities} on {@code targets}, or, when
     * {@code dependsOn} is set, on the companies its source finds; {@code stage} is 1 plus its source's stage. A LIMITED one
     * carries its {@code limitation} kind. {@code evidenceScope} is the evidence the member narrowed the selection to
     * (null when not narrowed): the requirement may read and cite nothing else. {@code parent} is the router requirement a
     * server requirement was split from (null for a router one).
     */
    record Planned(String id, String label, Set<ChatQueryType> types, Mode mode, String limitation,
            List<ChatCapability> capabilities, List<String> targets, TargetSource targetSource, List<String> evidenceScope,
            ChatRouteDecision.Dependency dependsOn, int stage, Origin origin, String parent) {
        /** Id and label suffixes of a concept requirement. */
        static final String CONCEPT_ID = "-c";
        static final String CONCEPT_LABEL = " — 개념 설명";

        public Planned {
            types = Set.copyOf(types);
            capabilities = List.copyOf(capabilities);
            targets = List.copyOf(targets);
            evidenceScope = evidenceScope == null ? null : List.copyOf(evidenceScope);
        }

        /** A router requirement. */
        Planned(String id, String label, Set<ChatQueryType> types, Mode mode, String limitation,
                List<ChatCapability> capabilities, List<String> targets, TargetSource targetSource,
                List<String> evidenceScope, ChatRouteDecision.Dependency dependsOn, int stage) {
            this(id, label, types, mode, limitation, capabilities, targets, targetSource, evidenceScope, dependsOn, stage,
                    Origin.ROUTER, null);
        }

        Planned limited(String kind) {
            return new Planned(id, label, types, Mode.LIMITED, kind, List.of(), List.of(), null, null, dependsOn, stage,
                    origin, parent);
        }

        /** The Q02 part of this requirement as a general requirement of its own. */
        Planned concept() {
            return new Planned(id + CONCEPT_ID, label + CONCEPT_LABEL, Set.of(ChatQueryType.Q02), Mode.GENERAL, null,
                    List.of(), List.of(), null, null, null, 1, Origin.CONCEPT, id);
        }
    }
}
