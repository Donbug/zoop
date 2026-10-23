package com.zoop.graph.snapshot;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Article;
import com.zoop.graph.snapshot.PublicGraphSnapshot.ArticleRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Company;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.MentionRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.Instant;
import java.time.LocalDate;
import java.time.Year;
import java.time.YearMonth;
import java.time.format.DateTimeParseException;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.Function;

/**
 * Strict reader for the app snapshot format (version 1). Unknown keys, broken references, unknown relation types
 * and unresolved geography are rejected as an unreadable snapshot instead of being dropped or guessed.
 */
public final class GraphSnapshotCodec {
    static final Set<String> RELATION_TYPES = Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS");
    static final Set<String> GEOGRAPHY = Set.of("domestic", "international");

    private GraphSnapshotCodec() {
    }

    public static PublicGraphSnapshot read(byte[] bytes, String expectedVersionId) {
        return read(bytes, expectedVersionId, false);
    }

    /** Only a round-bound reconstruction may preserve unclassified geography as null. Public snapshots stay strict. */
    public static PublicGraphSnapshot readReconstruction(byte[] bytes, String expectedVersionId) {
        if (!expectedVersionId.matches("brf-reconstructed-[0-9a-f]{64}")) throw invalid("reconstruction_identity");
        return read(bytes, expectedVersionId, true);
    }

    private static PublicGraphSnapshot read(byte[] bytes, String expectedVersionId, boolean reconstruction) {
        try {
            Obj root = StrictJson.parseObject(bytes).exactly(Set.of("snapshotFormat", "versionId", "sourceBundleId",
                    "companies", "issues", "relations", "articles", "evidence"));
            if (root.count("snapshotFormat") != PublicGraphSnapshot.FORMAT) throw invalid("snapshot_format");
            if (!root.string("versionId").equals(expectedVersionId)) throw invalid("version_mismatch");
            PublicGraphSnapshot snapshot = new PublicGraphSnapshot(PublicGraphSnapshot.FORMAT, root.string("versionId"),
                    root.stringOrNull("sourceBundleId"),
                    root.objects("companies").stream().map(GraphSnapshotCodec::company).toList(),
                    root.objects("issues").stream().map(GraphSnapshotCodec::issue).toList(),
                    root.objects("relations").stream().map(GraphSnapshotCodec::relation).toList(),
                    root.objects("articles").stream().map(GraphSnapshotCodec::article).toList(),
                    root.objects("evidence").stream().map(GraphSnapshotCodec::evidence).toList());
            if (reconstruction && !("briefing-reconstruction-v1:" + expectedVersionId).equals(snapshot.sourceBundleId()))
                throw invalid("reconstruction_binding");
            validate(snapshot, reconstruction);
            return snapshot;
        } catch (GraphSnapshotUnavailableException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new GraphSnapshotUnavailableException("snapshot_malformed", exception);
        }
    }

    private static Company company(Obj o) {
        o.keys(Set.of("companyId", "label"), Set.of("brandColor", "logoUrl"));
        return new Company(o.string("companyId"), o.string("label"), optional(o, "brandColor"), optional(o, "logoUrl"));
    }

    private static Issue issue(Obj o) {
        o.keys(Set.of("issueId", "label", "eventTime", "timePrecision", "geography", "geographyPolicyVersion",
                "geographyEvidenceIds", "articleIds", "evidenceIds", "mentions", "latestPublishedAt"),
                Set.of("period", "assertionStatus", "action", "target", "representativeMentionId"));
        return new Issue(o.string("issueId"), o.string("label"), o.stringOrNull("eventTime"), o.string("timePrecision"),
                optional(o, "period"), optional(o, "assertionStatus"), optional(o, "action"), optional(o, "target"),
                o.stringOrNull("geography"), o.string("geographyPolicyVersion"), o.strings("geographyEvidenceIds"),
                o.strings("articleIds"), o.strings("evidenceIds"), o.objects("mentions").stream().map(m -> {
                    m.exactly(Set.of("mentionId", "articleId", "articleVersion"));
                    return new MentionRef(m.string("mentionId"), m.string("articleId"), m.string("articleVersion"));
                }).toList(), optional(o, "representativeMentionId"), o.stringOrNull("latestPublishedAt"));
    }

    private static Relation relation(Obj o) {
        o.keys(Set.of("relationId", "relationType", "source", "target", "evidenceIds", "basis"),
                Set.of("role", "assertionStatus"));
        return new Relation(o.string("relationId"), o.string("relationType"), o.string("source"), o.string("target"),
                optional(o, "role"), optional(o, "assertionStatus"), o.strings("evidenceIds"),
                o.objects("basis").stream().map(GraphSnapshotCodec::basis).toList());
    }

    private static Basis basis(Obj o) {
        o.keys(Set.of("basisId", "relationType", "verifiedAt", "countries", "articles"), Set.of("validFrom", "validUntil"));
        return new Basis(o.string("basisId"), o.string("relationType"), o.string("verifiedAt"), optional(o, "validFrom"),
                optional(o, "validUntil"), o.strings("countries"), o.objects("articles").stream().map(a -> {
                    a.exactly(Set.of("articleId", "articleVersion"));
                    return new ArticleRef(a.string("articleId"), a.string("articleVersion"));
                }).toList());
    }

    private static Article article(Obj o) {
        o.exactly(Set.of("articleId", "version", "title", "url", "publishedAt"));
        return new Article(o.string("articleId"), o.string("version"), o.string("title"), o.string("url"),
                o.stringOrNull("publishedAt"));
    }

    private static Evidence evidence(Obj o) {
        o.exactly(Set.of("evidenceId", "articleId", "articleVersion", "start", "end"));
        return new Evidence(o.string("evidenceId"), o.string("articleId"), o.string("articleVersion"),
                o.count("start"), o.count("end"));
    }

    private static String optional(Obj o, String name) {
        return o.has(name) ? o.stringOrNull(name) : null;
    }

    private static void validate(PublicGraphSnapshot s, boolean reconstruction) {
        Set<String> companies = unique(s.companies(), Company::companyId, "company");
        Set<String> issues = unique(s.issues(), Issue::issueId, "issue");
        unique(s.relations(), Relation::relationId, "relation");
        Set<String> articles = unique(s.articles(), a -> a.articleId() + "@" + a.version(), "article");
        Set<String> evidence = unique(s.evidence(), Evidence::evidenceId, "evidence");
        for (Evidence e : s.evidence()) {
            if (!articles.contains(e.articleId() + "@" + e.articleVersion()) || e.start() >= e.end()) {
                throw invalid("evidence_reference");
            }
        }
        for (Article a : s.articles()) {
            // null is an unknown publication time (kept, but never before an asOf); any other value must parse.
            if (a.publishedAt() != null && !isDateOrInstant(a.publishedAt())) throw invalid("article_published_at");
        }
        for (Relation r : s.relations()) {
            for (Basis b : r.basis()) {
                if (!isInstant(b.verifiedAt()) || !isDateOrNull(b.validFrom()) || !isDateOrNull(b.validUntil())) {
                    throw invalid("relation_basis_time");
                }
                if (b.basisId().isBlank() || b.relationType().isBlank()) throw invalid("relation_basis");
                // Every named article version must be pinned in this snapshot.
                if (b.articles().stream().anyMatch(a -> !articles.contains(a.articleId() + "@" + a.articleVersion()))) {
                    throw invalid("relation_basis_article");
                }
            }
        }
        for (Issue issue : s.issues()) {
            boolean unclassified = reconstruction && issue.geography() == null
                    && "not_recorded".equals(issue.geographyPolicyVersion()) && issue.geographyEvidenceIds().isEmpty();
            if (!unclassified && (issue.geography() == null || !GEOGRAPHY.contains(issue.geography()))) throw invalid("issue_geography");
            if (!unclassified && (issue.geographyEvidenceIds().isEmpty() || !evidence.containsAll(issue.geographyEvidenceIds()))) {
                throw invalid("issue_geography_evidence");
            }
            if (!matchesPrecision(issue.eventTime(), issue.timePrecision())) throw invalid("issue_event_time");
            if (issue.latestPublishedAt() != null && !isDateOrInstant(issue.latestPublishedAt())) {
                throw invalid("issue_published_at");
            }
            if (!evidence.containsAll(issue.evidenceIds())) throw invalid("issue_evidence_reference");
            Set<String> mentionIds = new HashSet<>();
            for (MentionRef m : issue.mentions()) {
                // A mention cites one of the issue's own pinned articles, so the asOf filter on articles also covers it.
                if (!mentionIds.add(m.mentionId()) || !issue.articleIds().contains(m.articleId())
                        || !articles.contains(m.articleId() + "@" + m.articleVersion())) {
                    throw invalid("issue_mention_reference");
                }
            }
            if (issue.representativeMentionId() != null && !mentionIds.contains(issue.representativeMentionId())) {
                throw invalid("issue_representative_mention");
            }
            for (String articleId : issue.articleIds()) {
                if (s.articles().stream().noneMatch(a -> a.articleId().equals(articleId))) {
                    throw invalid("issue_article_reference");
                }
            }
        }
        for (Relation r : s.relations()) {
            if (!RELATION_TYPES.contains(r.relationType())) throw invalid("relation_type");
            boolean follows = "FOLLOWS".equals(r.relationType());
            if (!issues.contains(r.source()) || !(follows ? issues : companies).contains(r.target())) {
                throw invalid("relation_endpoint");
            }
            if (!follows && r.evidenceIds().isEmpty()) throw invalid("relation_without_evidence");
            if (!evidence.containsAll(r.evidenceIds())) throw invalid("relation_evidence_reference");
        }
    }

    /** The value must have exactly the stated precision; a date is never widened to an invented midnight. */
    static boolean matchesPrecision(String value, String precision) {
        if (precision == null) return false;
        return switch (precision) {
            case "unknown" -> value == null;
            case "year" -> value != null && parses(() -> Year.parse(value));
            case "month" -> value != null && parses(() -> YearMonth.parse(value));
            case "day" -> isDate(value);
            case "datetime" -> isInstant(value);
            default -> false;
        };
    }

    private static boolean isDateOrInstant(String value) {
        return isDate(value) || isInstant(value);
    }

    private static boolean isDateOrNull(String value) {
        return value == null || isDate(value);
    }

    private static boolean isDate(String value) {
        return value != null && parses(() -> LocalDate.parse(value));
    }

    private static boolean isInstant(String value) {
        return value != null && parses(() -> Instant.parse(value));
    }

    private static boolean parses(Runnable parse) {
        try {
            parse.run();
            return true;
        } catch (DateTimeParseException exception) {
            return false;
        }
    }

    private static <T> Set<String> unique(List<T> items, Function<T, String> key, String name) {
        Set<String> seen = new HashSet<>();
        for (T item : items) {
            if (!seen.add(key.apply(item))) throw invalid("duplicate_" + name);
        }
        return seen;
    }

    private static GraphSnapshotUnavailableException invalid(String reason) {
        return new GraphSnapshotUnavailableException("snapshot_invalid:" + reason);
    }
}
