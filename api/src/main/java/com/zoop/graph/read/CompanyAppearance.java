package com.zoop.graph.read;

import com.zoop.graph.snapshot.PublicGraphSnapshot.Company;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/**
 * Catalog appearance (logo, brand colour) for company nodes. A snapshot keeps only what the AI handoff states (id,
 * label), so the read fills a missing logo or colour from the companies catalog. A value the snapshot carries wins;
 * the snapshot file itself is never changed.
 */
final class CompanyAppearance {
    private CompanyAppearance() {
    }

    /** One query for all ids; ids the catalog does not know are simply absent. */
    static Map<String, Company> of(NamedParameterJdbcTemplate jdbc, Collection<String> ids) {
        if (ids.isEmpty()) return Map.of();
        Map<String, Company> found = new HashMap<>();
        jdbc.query("SELECT id, name, brand_color, logo_url FROM companies WHERE id IN (:ids)",
                new MapSqlParameterSource("ids", List.copyOf(ids)), (rs, n) -> new Company(rs.getString("id"),
                        rs.getString("name"), rs.getString("brand_color"), rs.getString("logo_url")))
                .forEach(c -> found.put(c.companyId(), c));
        return found;
    }

    /** The snapshot company with a missing brand colour or logo taken from the catalog row, if there is one. */
    static Company fill(Company snapshot, Company catalog) {
        if (snapshot == null) return catalog;
        if (catalog == null) return snapshot;
        return new Company(snapshot.companyId(), snapshot.label(),
                snapshot.brandColor() != null ? snapshot.brandColor() : catalog.brandColor(),
                snapshot.logoUrl() != null ? snapshot.logoUrl() : catalog.logoUrl());
    }
}
