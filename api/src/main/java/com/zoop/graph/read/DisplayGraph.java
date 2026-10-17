package com.zoop.graph.read;

import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;

/**
 * The display graph of one filtered snapshot (prototype {@code dataset.build_dataset} rules):
 * approved relations grouped per (relationType, source, target) into one display edge, plus derived SHARES_ISSUE
 * edges between companies that share a remaining public issue. Derived edges are never stored in a snapshot.
 */
public final class DisplayGraph {
    static final Set<String> COMPANY_LINKS = Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO");
    static final String FOLLOWS_SUMMARY = "후속 사건";
    static final String ROLE_FALLBACK = "직접 관련";
    static final String STRUCTURAL_FALLBACK = "구조적 관계";

    public record Edge(String id, String source, String target, String relationType, String role, String summary,
            String assertionStatus, boolean derived, List<String> via, List<String> evidenceIds,
            List<String> relationIds) { }

    final PublicGraphSnapshot snapshot;
    final Map<String, Issue> issues = new LinkedHashMap<>();
    final Map<String, PublicGraphSnapshot.Company> companies = new LinkedHashMap<>();
    final Map<String, Edge> edges = new LinkedHashMap<>();
    /** issue id -> linked company ids (INVOLVES / STRUCTURALLY_RELATED_TO), in edge order. */
    final Map<String, Set<String>> issueCompanies = new LinkedHashMap<>();
    /** company id -> linked issue ids. */
    final Map<String, Set<String>> companyIssues = new LinkedHashMap<>();
    /** issue id -> issues it follows or that follow it. */
    final Map<String, Set<String>> followsNeighbours = new LinkedHashMap<>();

    private DisplayGraph(PublicGraphSnapshot snapshot) {
        this.snapshot = snapshot;
    }

    public static DisplayGraph of(PublicGraphSnapshot snapshot) {
        DisplayGraph g = new DisplayGraph(snapshot);
        snapshot.issues().forEach(i -> g.issues.put(i.issueId(), i));
        snapshot.companies().forEach(c -> g.companies.put(c.companyId(), c));
        Map<String, List<Relation>> grouped = new LinkedHashMap<>();
        for (Relation r : snapshot.relations()) {
            grouped.computeIfAbsent(r.relationType() + "|" + r.source() + "|" + r.target(), k -> new ArrayList<>()).add(r);
        }
        for (List<Relation> rels : grouped.values()) {
            Relation first = rels.get(0);
            String id = edgeId(first.relationType(), first.source(), first.target());
            List<String> roles = rels.stream().map(Relation::role).filter(Objects::nonNull).toList();
            String role = roles.isEmpty() ? null : RoleLabels.display(roles.get(0));
            g.edges.put(id, new Edge(id, first.source(), first.target(), first.relationType(), role,
                    summary(first.relationType(), roles), rels.stream().map(Relation::assertionStatus)
                            .filter(Objects::nonNull).findFirst().orElse(null), false, List.of(),
                    rels.stream().flatMap(r -> r.evidenceIds().stream()).distinct().toList(),
                    rels.stream().map(Relation::relationId).toList()));
            if (COMPANY_LINKS.contains(first.relationType())) {
                g.issueCompanies.computeIfAbsent(first.source(), k -> new LinkedHashSet<>()).add(first.target());
                g.companyIssues.computeIfAbsent(first.target(), k -> new LinkedHashSet<>()).add(first.source());
            } else {
                g.followsNeighbours.computeIfAbsent(first.source(), k -> new LinkedHashSet<>()).add(first.target());
                g.followsNeighbours.computeIfAbsent(first.target(), k -> new LinkedHashSet<>()).add(first.source());
            }
        }
        // Derived pairs: companies sharing a remaining public issue. Not a supply/customer relation.
        Map<String, List<String>> pairVia = new LinkedHashMap<>();
        for (var entry : g.issueCompanies.entrySet()) {
            List<String> ids = new ArrayList<>(new TreeSet<>(entry.getValue()));
            for (int a = 0; a < ids.size(); a++) {
                for (int b = a + 1; b < ids.size(); b++) {
                    pairVia.computeIfAbsent(ids.get(a) + "|" + ids.get(b), k -> new ArrayList<>()).add(entry.getKey());
                }
            }
        }
        pairVia.forEach((pair, via) -> {
            String[] ends = pair.split("\\|", 2);
            String id = edgeId("SHARES_ISSUE", ends[0], ends[1]);
            g.edges.put(id, new Edge(id, ends[0], ends[1], "SHARES_ISSUE", null, "같은 사건 " + via.size() + "건", null,
                    true, List.copyOf(via), List.of(), List.of()));
        });
        return g;
    }

    /** Newest event first, unknown time last; ties by newest article, then id (prototype {@code sort_recent}). */
    static final Comparator<Issue> RECENT = Comparator
            .comparing((Issue i) -> eventStart(i), Comparator.reverseOrder())
            .thenComparing(Issue::latestPublishedAt, Comparator.nullsLast(Comparator.reverseOrder()))
            .thenComparing(Issue::issueId);

    static String eventStart(Issue i) {
        if (i.eventTime() == null) return "";
        return switch (i.timePrecision()) {
            case "year" -> i.eventTime() + "-01-01";
            case "month" -> i.eventTime() + "-01";
            default -> i.eventTime();
        };
    }

    List<Issue> issuesOf(String companyId) {
        return companyIssues.getOrDefault(companyId, Set.of()).stream().map(issues::get).sorted(RECENT).toList();
    }

    /** The first role with a Korean label (prototype {@code _role_summary}); an unknown phrase falls back. */
    private static String summary(String relationType, List<String> roles) {
        if ("FOLLOWS".equals(relationType)) return FOLLOWS_SUMMARY;
        String label = roles.stream().map(RoleLabels::label).filter(Objects::nonNull).findFirst().orElse(null);
        if (label != null) return label;
        return "STRUCTURALLY_RELATED_TO".equals(relationType) ? STRUCTURAL_FALLBACK : ROLE_FALLBACK;
    }

    /** {@code edge-} + first 16 hex of SHA-256("type|source|target"); scope is not needed because one end is an issue. */
    static String edgeId(String relationType, String source, String target) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest((relationType + "|" + source + "|" + target).getBytes(StandardCharsets.UTF_8));
            return "edge-" + HexFormat.of().formatHex(hash).substring(0, 16);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
