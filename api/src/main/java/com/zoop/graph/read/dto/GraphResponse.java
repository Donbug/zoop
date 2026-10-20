package com.zoop.graph.read.dto;

import com.zoop.common.response.SectionFailure;
import java.util.List;

/** OpenAPI {@code GraphResponse}, {@code GraphNode}, {@code GraphEdge} and {@code GraphMetadata}. Every field is always present. */
public record GraphResponse(List<Node> nodes, List<Edge> edges, Metadata metadata) {
    public GraphResponse {
        nodes = List.copyOf(nodes);
        edges = List.copyOf(edges);
    }

    public record Node(String id, String kind, String label, boolean isFocus, boolean holding, boolean watch,
            String brandColor, String logoUrl, String eventTime, String timePrecision, String action, String target,
            Integer evidenceCount, String geography) { }

    public record Edge(String id, String source, String target, String relationType, String role, String summary,
            String assertionStatus, boolean derived, List<String> via, List<String> evidenceIds, String validity) { }

    public record Metadata(String source, String asOf, String graphVersion, String mode, boolean truncated,
            String emptyReason, List<String> focusCompanyIds, Integer depth, int limit, String requestId,
            boolean partial, List<SectionFailure> failures, String personalFilter) { }
}
