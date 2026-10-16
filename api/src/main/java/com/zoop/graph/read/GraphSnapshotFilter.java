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

    public static PublicGraphSnapshot apply(PublicGraphSnapshot s, Instant asOf, DisclosureExclusions exclusions) {
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
                .filter(i -> !i.evidenceIds().isEmpty() && !i.geographyEvidenceIds().isEmpty())
                .toList();
        Set<String> kept = issues.stream().map(Issue::issueId).collect(Collectors.toCollection(HashSet::new));

        List<Relation> relations = s.relations().stream()
                .filter(r -> !exclusions.relationIds().contains(r.relationId()))
                .filter(r -> kept.contains(r.source()) && (!"FOLLOWS".equals(r.relationType()) || kept.contains(r.target())))
                .filter(r -> evidenceIds.containsAll(r.evidenceIds()))
                .filter(r -> asOf == null || !"STRUCTURALLY_RELATED_TO".equals(r.relationType())
                        || r.basis().stream().anyMatch(b -> !Instant.parse(b.verifiedAt()).isAfter(asOf)))
                .toList();
        return new PublicGraphSnapshot(s.snapshotFormat(), s.versionId(), s.sourceBundleId(), s.companies(), issues,
                relations, s.articles().stream().filter(a -> articles.contains(articleKey(a))).toList(), evidence);
    }

    /**
     * A full timestamp counts once it is at or before asOf. A date-only value carries no time or zone, so it is compared
     * as a date: it counts only if it is before asOf's calendar date at UTC-12, the last zone to change date, and the
     * same day never counts. The date is never given a time.
     */
    static boolean publishedBy(String value, Instant asOf) {
        if (value.length() == 10) return LocalDate.parse(value).isBefore(LocalDate.ofInstant(asOf, LAST_DATE_LINE));
        return !Instant.parse(value).isAfter(asOf);
    }

    private static Issue withEvidence(Issue i, Set<String> evidenceIds) {
        return new Issue(i.issueId(), i.label(), i.eventTime(), i.timePrecision(), i.action(), i.target(), i.geography(),
                i.geographyPolicyVersion(), i.geographyEvidenceIds().stream().filter(evidenceIds::contains).toList(),
                i.articleIds(), i.evidenceIds().stream().filter(evidenceIds::contains).toList(), i.latestPublishedAt());
    }

    private static String articleKey(Article a) {
        return a.articleId() + "@" + a.version();
    }
}
