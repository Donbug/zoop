package com.zoop.chat.orchestrator;

import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolResult;
import java.util.List;
import java.util.Set;
import java.util.function.Supplier;

/**
 * The agent path of a run (ZOOP-AIG-001 v0.11 6.3, MCP actions contract 3.4): Luna chooses and chains the ZOOP MCP read tools
 * the server allowed, the server decides every call it proposes, and the run ends with Luna's answer and exactly the results
 * of the calls that ran. The orchestrator checks that answer like a generated one, against those results.
 *
 * <p>The production implementation is {@code com.zoop.chat.mcp.ChatMcpAgent}; without it every run takes the direct path
 * (the server plans and reads, Luna only writes).
 */
public interface ChatAgentPath {
    /**
     * Checks whether a new agent run may start. Production performs the MCP preflight and circuit decision here; false means
     * the engine starts the direct path before any agent model request. Test and non-MCP paths are available by default.
     */
    default boolean available() {
        return true;
    }

    /** The capabilities the agent may be given (those exposed as MCP tools). */
    Set<ChatCapability> tools();

    /**
     * Runs the agent for {@code requirements} with {@code tools}. Every step is one model call made through {@code steps},
     * which applies the run's deadline guard and stage limit. Model failures surface as {@link ChatModels.Failure}.
     */
    Outcome run(ChatRun run, ChatRunControl control, List<ChatModels.AgentRequirement> requirements,
            List<ChatCapability> tools, int maxCitations, Steps steps);

    /** Runs one agent step under the engine's guard and limit, and says when no further round fits. */
    interface Steps {
        ChatModels.AgentStep run(Supplier<ChatModels.AgentStep> step);

        /**
         * Whether the time left fits only one more step: the agent then denies what it is asked, so that step is the one
         * that writes the answer (the last 10 s start no new tool, MCP actions contract 3.2).
         */
        boolean closing();
    }

    /**
     * The final answer, the results of the calls that ran (as the model received them), and what the run decided: steps,
     * approved and denied calls.
     */
    record Outcome(ChatGeneratedAnswer answer, List<ChatToolResult> results, int steps, int approved, int denied) {
        public Outcome {
            results = List.copyOf(results);
        }
    }
}
