package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.tool.ChatToolResult;
import java.util.List;
import java.util.Set;

/**
 * What the answer generator gets (implementation plan stage 5 {@code BranchContext}): the question chain, the frozen context
 * and one branch per answerable requirement with its tool results. Full article texts are never included.
 * {@code maxCitations} is the number of distinct evidence ids the whole answer may cite.
 */
public record ChatBranchContext(List<ChatRun.Turn> turns, ChatFrozenContext context, List<Branch> branches,
        int maxCitations) {
    public ChatBranchContext {
        turns = List.copyOf(turns);
        branches = List.copyOf(branches);
    }

    /**
     * One requirement. {@code general} is a Q02 concept answered without tools. {@code noneFound} is a lookup that
     * succeeded and found nothing within its scope, without being cut by a limit: the generator may say so.
     * {@code parent} is set for a requirement the server split off a router requirement ({@link ChatPlan.Origin}), and
     * {@code avoidNames} are the company and issue labels its parent's reads returned, which its text must not name.
     */
    public record Branch(String requirementId, String label, Set<ChatQueryType> types, boolean general,
            List<ChatToolResult> results, boolean noneFound, String parent, List<String> avoidNames) {
        public Branch {
            types = Set.copyOf(types);
            results = List.copyOf(results);
            avoidNames = List.copyOf(avoidNames);
        }

        /** A router requirement's branch. */
        public Branch(String requirementId, String label, Set<ChatQueryType> types, boolean general,
                List<ChatToolResult> results, boolean noneFound) {
            this(requirementId, label, types, general, results, noneFound, null, List.of());
        }
    }
}
