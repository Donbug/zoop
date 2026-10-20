package com.zoop.graph.read.dto;

import com.zoop.common.response.Metadata;
import com.zoop.company.graph.CompanyGraphSnapshot.BasisOut;
import java.util.List;

/**
 * OpenAPI {@code EdgeDetail} ({@code getCompanyRelation}); every key is serialized, nulls included. validity is the
 * business relation status of a structural edge at metadata.asOf, null for edges without structural basis.
 */
public record EdgeDetail(String id, String relationType, boolean derived, boolean directed, EndpointRef source,
        EndpointRef target, String role, String summary, List<String> roles, String assertionStatus,
        List<String> evidenceIds, List<BasisOut> basis, List<String> relationIds, Verification verification,
        List<ViaIssue> via, String explanation, String validity, Metadata metadata) {

    /** logoUrl and brandColor are set for a company end (null when the catalog has none) and null for an issue end. */
    public record EndpointRef(String id, String kind, String label, String logoUrl, String brandColor) { }

    /** ALLOW for an approved public relation; not_applicable for a derived edge, which is never verified. */
    public record Verification(String status, String note) { }

    public record ViaIssue(String title, String id, String eventTime, String timePrecision, List<String> evidenceIds) { }
}
