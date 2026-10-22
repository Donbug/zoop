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
     */
    public record Branch(String requirementId, String label, Set<ChatQueryType> types, boolean general,
            List<ChatToolResult> results, boolean noneFound) {
        public Branch {
            types = Set.copyOf(types);
            results = List.copyOf(results);
        }
    }
}
