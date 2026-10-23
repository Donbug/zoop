package com.zoop.chat.tool;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.util.Optional;
import org.springframework.stereotype.Component;

/** {@code company.read}: a company visible in the pinned graph and the evidence of its approved relations. */
@Component
public class CompanyReadTool extends GraphTargetTool {
    public CompanyReadTool(PublicGraphReader reader, ChatEvidenceAccess access) {
        super(reader, access);
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.COMPANY_READ;
    }

    @Override
    Optional<GraphContextLookup.Target> find(GraphContextLookup lookup, String id) {
        return lookup.find(id).filter(t -> "company".equals(t.kind()));
    }
}
