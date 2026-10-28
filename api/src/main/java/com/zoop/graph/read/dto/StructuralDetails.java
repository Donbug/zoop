package com.zoop.graph.read.dto;

import java.time.Instant;
import java.util.List;

/** FS023: an operator-mapped supply chain, never causality or price direction. */
public record StructuralDetails(String status, String reason, List<Path> paths) {
    public StructuralDetails { paths = List.copyOf(paths); }
    public static StructuralDetails notApplicable() {
        return new StructuralDetails("not_applicable", null, List.of());
    }
    public static StructuralDetails unavailable(String reason) {
        return new StructuralDetails("unavailable", reason, List.of());
    }
    public record Company(String id, String label) { }
    public record Path(String relationId, List<Company> companies, List<Link> links) {
        public Path { companies = List.copyOf(companies); links = List.copyOf(links); }
    }
    public record Link(String basisId, String relationType, String supplierCompanyId, String customerCompanyId,
            String businessScope, String productScope, String validFrom, String validUntil, String validity,
            Instant verifiedAt, List<String> countries, List<String> evidenceIds) {
        public Link { countries = List.copyOf(countries); evidenceIds = List.copyOf(evidenceIds); }
    }
}
