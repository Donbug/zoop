package com.zoop.chat.tool;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.util.Optional;
import org.springframework.stereotype.Component;

/**
 * {@code evidence.resolve}: evidence ids the pinned graph lists, labelled with their article title, passed on only when the
 * public evidence read can read them now. A span cited only by a structural basis is listed but not cited; the evidence read
 * is what admits it, exactly as for {@code GET /api/v1/evidence/{id}}.
 */
@Component
public class EvidenceResolveTool extends GraphTargetTool {
    public EvidenceResolveTool(PublicGraphReader reader, ChatEvidenceAccess access) {
        super(reader, access);
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.EVIDENCE_RESOLVE;
    }

    @Override
    Optional<GraphContextLookup.Target> find(GraphContextLookup lookup, String id) {
        return lookup.find(id).filter(t -> "evidence".equals(t.kind())).or(() -> lookup.listedEvidence(id));
    }

    /** Evidence the read refuses is not found; one left unread by the limit is reported as truncated instead. */
    @Override
    boolean keptWithoutEvidence() {
        return false;
    }
}
