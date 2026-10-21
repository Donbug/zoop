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
     * One planned requirement. TOOLS requirements read {@code capabilities} on {@code targets}, or, when
     * {@code dependsOn} is set, on the companies its source finds; {@code stage} is 1 plus its source's stage. A LIMITED one
     * carries its {@code limitation} kind.
     */
    record Planned(String id, String label, Set<ChatQueryType> types, Mode mode, String limitation,
            List<ChatCapability> capabilities, List<String> targets, ChatRouteDecision.Dependency dependsOn, int stage) {
        public Planned {
            types = Set.copyOf(types);
            capabilities = List.copyOf(capabilities);
            targets = List.copyOf(targets);
        }

        Planned limited(String kind) {
            return new Planned(id, label, types, Mode.LIMITED, kind, List.of(), List.of(), dependsOn, stage);
        }
    }
}
