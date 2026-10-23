package com.zoop.chat.tool;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.util.Optional;
import org.springframework.stereotype.Component;

/** {@code issue.read}: an issue visible in the pinned graph, its companies and its evidence. */
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
}
