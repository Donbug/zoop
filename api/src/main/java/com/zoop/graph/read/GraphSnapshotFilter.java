package com.zoop.graph.read;

import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Article;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Narrows the selected version's snapshot for one request, in two independent steps:
 * <ol>
 * <li>asOf (only when requested): keep what was already published at that time inside the pinned version.</li>
 * <li>current exclusions: always, so a past version never re-exposes something withdrawn today.</li>
 * </ol>
 * An issue is dropped once all of its evidence is gone; a relation of any type, FOLLOWS included, is dropped once any
 * of its evidence is gone (a relation without evidence IDs is kept). Derived SHARES_ISSUE edges are computed afterwards.
 */
public final class GraphSnapshotFilter {
    private static final ZoneOffset LAST_DATE_LINE = ZoneOffset.ofHours(-12);

    private GraphSnapshotFilter() {
    }

    /** All round consumers share this closed projection; derived edges are built only afterwards. */
    static PublicGraphSnapshot briefing(PublicGraphSnapshot s, com.zoop.graph.version.BriefingGraphLookup.Basis basis) {
        Set<String> selected = Set.copyOf(basis.keyIssueIds());
        var issues = s.issues().stream().filter(i -> selected.contains(i.issueId())).toList();
        var relations = s.relations().stream().filter(r -> selected.contains(r.source())
                && (!"FOLLOWS".equals(r.relationType()) || selected.contains(r.target()))).toList();
        Set<String> companies = new HashSet<>(basis.companyIds());
        relations.stream().filter(r -> !"FOLLOWS".equals(r.relationType())).forEach(r -> companies.add(r.target()));
        Set<String> cited = new HashSet<>();
        issues.forEach(i -> { cited.addAll(i.evidenceIds()); cited.addAll(i.geographyEvidenceIds()); });
        relations.forEach(r -> cited.addAll(r.evidenceIds()));
        Set<String> membershipArticles = new HashSet<>();
        relations.forEach(r -> r.basis().forEach(b -> b.articles().forEach(a ->
                membershipArticles.add(a.articleId() + "@" + a.articleVersion()))));
        Set<String> impactCitations = relations.stream().filter(r -> "INVOLVES".equals(r.relationType()))
                .flatMap(r -> r.evidenceIds().stream()).collect(Collectors.toSet());
        // Preserve candidates for receipt-proven impact quotes, but only for INVOLVES edges inside this round.
        // These spans are not added to an issue or relation's evidence ids and confer no membership on their own.
        for (Evidence span : s.evidence()) {
            if (impactCitations.contains(span.evidenceId())) {
                membershipArticles.add(span.articleId() + "@" + span.articleVersion());
            }
        }
        var evidence = s.evidence().stream().filter(e -> cited.contains(e.evidenceId())
                || membershipArticles.contains(e.articleId() + "@" + e.articleVersion())).toList();
        Set<String> articles = new HashSet<>(membershipArticles);
        evidence.forEach(e -> articles.add(e.articleId() + "@" + e.articleVersion()));
        issues.forEach(i -> i.mentions().forEach(m -> articles.add(m.articleId() + "@" + m.articleVersion())));
        return new PublicGraphSnapshot(s.snapshotFormat(), s.versionId(), s.sourceBundleId(),
                s.companies().stream().filter(c -> companies.contains(c.companyId())).toList(), issues, relations,
                s.articles().stream().filter(a -> articles.contains(articleKey(a))).toList(), evidence);
    }

    public static PublicGraphSnapshot apply(PublicGraphSnapshot s, Instant asOf, DisclosureExclusions exclusions) {
        return apply(s, asOf, exclusions, false);
    }

    static PublicGraphSnapshot apply(PublicGraphSnapshot s, Instant asOf, DisclosureExclusions exclusions, boolean reconstruction) {
        Set<String> articles = s.articles().stream()
                .filter(a -> asOf == null || publishedBy(a.publishedAt(), asOf))
                .map(GraphSnapshotFilter::articleKey).collect(Collectors.toSet());
        List<Evidence> evidence = s.evidence().stream()
                .filter(e -> articles.contains(e.articleId() + "@" + e.articleVersion()))
                .filter(e -> !exclusions.evidenceIds().contains(e.evidenceId())).toList();
        Set<String> evidenceIds = evidence.stream().map(Evidence::evidenceId).collect(Collectors.toSet());
        Set<String> articleIds = s.articles().stream().filter(a -> articles.contains(articleKey(a)))
                .map(Article::articleId).collect(Collectors.toSet());

        List<Issue> issues = s.issues().stream()
                .filter(i -> !exclusions.issueIds().contains(i.issueId()))
                .filter(i -> asOf == null || (publishedBy(i.latestPublishedAt(), asOf) && articleIds.containsAll(i.articleIds())))
                .map(i -> withEvidence(i, evidenceIds))
                .filter(i -> !i.evidenceIds().isEmpty() && (!i.geographyEvidenceIds().isEmpty() || (reconstruction && i.geography() == null)))
                .toList();
        Set<String> kept = issues.stream().map(Issue::issueId).collect(Collectors.toCollection(HashSet::new));

        List<Relation> relations = s.relations().stream()
                .filter(r -> !exclusions.relationIds().contains(r.relationId()))
                .filter(r -> kept.contains(r.source()) && (!"FOLLOWS".equals(r.relationType()) || kept.contains(r.target())))
                .filter(r -> evidenceIds.containsAll(r.evidenceIds()))
                .map(r -> verifiedBasisOnly(r, asOf))
                .filter(r -> !"STRUCTURALLY_RELATED_TO".equals(r.relationType()) || !r.basis().isEmpty())
                .toList();
        return new PublicGraphSnapshot(s.snapshotFormat(), s.versionId(), s.sourceBundleId(), s.companies(), issues,
                relations, s.articles().stream().filter(a -> articles.contains(articleKey(a))).toList(), evidence);
    }

    /**
     * FS042 visibility: a structural basis counts once it was verified by asOf. Its validity dates never hide it; a
     * not-yet-started or ended business relation stays visible and is told apart by its status, not removed.
     */
    /** At asOf a relation carries only the bases verified by then, so later bases never leak into details or status. */
    private static Relation verifiedBasisOnly(Relation r, Instant asOf) {
        if (asOf == null || !"STRUCTURALLY_RELATED_TO".equals(r.relationType())) return r;
        return new Relation(r.relationId(), r.relationType(), r.source(), r.target(), r.role(), r.assertionStatus(),
                r.evidenceIds(), r.basis().stream().filter(b -> verifiedBy(b, asOf)).toList());
    }

    static boolean verifiedBy(PublicGraphSnapshot.Basis b, Instant asOf) {
        return !Instant.parse(b.verifiedAt()).isAfter(asOf);
    }

    /**
     * A full timestamp counts once it is at or before asOf. A date-only value carries no time or zone, so it is compared
     * as a date: it counts only if it is before asOf's calendar date at UTC-12, the last zone to change date, and the
     * same day never counts. The date is never given a time. An unknown time (null) never counts, so undated articles
     * appear only without asOf.
     */
    static boolean publishedBy(String value, Instant asOf) {
        if (value == null) return false;
        if (value.length() == 10) return LocalDate.parse(value).isBefore(LocalDate.ofInstant(asOf, LAST_DATE_LINE));
        return !Instant.parse(value).isAfter(asOf);
    }

    private static Issue withEvidence(Issue i, Set<String> evidenceIds) {
        return new Issue(i.issueId(), i.label(), i.eventTime(), i.timePrecision(), i.period(), i.assertionStatus(),
                i.action(), i.target(), i.geography(), i.geographyPolicyVersion(),
                i.geographyEvidenceIds().stream().filter(evidenceIds::contains).toList(), i.articleIds(),
                i.evidenceIds().stream().filter(evidenceIds::contains).toList(), i.mentions(),
                i.representativeMentionId(), i.latestPublishedAt());
    }

    private static String articleKey(Article a) {
        return a.articleId() + "@" + a.version();
    }
}
