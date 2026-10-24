package com.zoop.chat.tool;

import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.util.List;
import java.util.Optional;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;

/**
 * {@code company.read}: a company visible in the pinned graph, its catalog profile (when the catalog has a business summary)
 * and the evidence of its approved relations. The profile comes first, so a company is described even before any relation
 * evidence exists.
 */
@Component
public class CompanyReadTool extends GraphTargetTool {
    private final ChatCompanyProfiles profiles;

    public CompanyReadTool(PublicGraphReader reader, ChatEvidenceAccess access, ChatCompanyProfiles profiles) {
        super(reader, access);
        this.profiles = profiles;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.COMPANY_READ;
    }

    @Override
    Optional<GraphContextLookup.Target> find(GraphContextLookup lookup, String id) {
        return lookup.find(id).filter(t -> "company".equals(t.kind()));
    }

    @Override
    List<String> ownEvidence(GraphContextLookup.Target target) {
        try {
            return profiles.forCompany(target.id()).map(q -> List.of(q.evidenceId())).orElse(List.of());
        } catch (DataAccessException unavailable) {
            throw new ChatToolUnavailable("the profile of " + target.id() + " cannot be read", unavailable);
        }
    }
}
