package com.zoop.chat.tool;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.util.List;
import java.util.Optional;
import org.springframework.stereotype.Component;

/**
 * {@code issue.read}: an issue visible in the pinned graph, its companies and its evidence. A company id reads the visible
 * issues that company is involved in or structurally related to, newest first (decision of 2026-10-27), so a question that
 * names only a company can still be answered from its issues.
 */
@Component
public class IssueReadTool extends GraphTargetTool {
    public IssueReadTool(PublicGraphReader reader, ChatEvidenceAccess access) {
        super(reader, access);
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.ISSUE_READ;
    }

    @Override
    Optional<GraphContextLookup.Target> find(GraphContextLookup lookup, String id) {
        return lookup.find(id).filter(t -> "issue".equals(t.kind()));
    }

    @Override
    List<GraphContextLookup.Target> targets(GraphContextLookup lookup, String id) {
        var issue = find(lookup, id);
        return issue.isPresent() ? List.of(issue.get()) : lookup.issuesOf(id);
    }
}
