package com.zoop.graph.read.dto;

import com.zoop.common.response.Metadata;
import java.util.List;

/** OpenAPI {@code ImpactPath}: only relationships visible in the pinned public snapshot are represented. */
public record ImpactPath(String companyId, String issueId, List<Step> steps, Metadata metadata) {
    public ImpactPath {
        steps = List.copyOf(steps);
    }

    public record Step(String id, String kind, String reason, List<String> evidenceIds) {
        public Step {
            evidenceIds = List.copyOf(evidenceIds);
        }
    }
}
