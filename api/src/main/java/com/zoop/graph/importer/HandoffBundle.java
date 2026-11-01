package com.zoop.graph.importer;

import java.util.List;
import java.util.Map;

/**
 * The parts of a fully validated {@code zoop-graph-handoff-bundle-7} that the import maps. Every field here has passed the
 * closed schema, the reference closure and the id formulas of {@link HandoffBundleVerifier}; nothing is trusted from the producer
 * that the verifier did not check. The snapshot writer reads the fields this model does not type ({@code period}, source events,
 * the representative, per-basis relation key, type, countries and source articles) from the verified raw bundle; the issue's
 * original {@code mentions[]} (S2 values with {@code verification: "none"}), the issue's {@code fieldProvenance} (which mentions
 * state each selected headline value, whether the operator's representative or unanimity selected it, and which of
 * {@code eventTime}/{@code period} an operator verdict withheld: a selection record, never a verification) and its operator
 * {@code fieldVerdicts} (per-mention ALLOW/HOLD/REJECT judgements of one original {@code eventTime} or {@code period} string,
 * each with its own-article evidence), all checked by the verifier but not typed here, and the provenance the snapshot has no
 * place for (decisions, source references, source events it cannot pin to an issue article) stay in the retained receipt and
 * are never dropped silently. The typed and the snapshot headline values are the ones the verifier recomputed: a withheld
 * {@code eventTime} or {@code period} is {@code null} ({@code eventTime} with {@code unknown} precision) there, while the
 * receipt's mentions and verdicts still hold every original value. {@code approvals} is the effective eligibility basis of every S3
 * relation the edges rest on (automatic verdict or an operator's final approval); the verifier recomputed the relation literals
 * from it. Each article's {@code textSha256} and declared {@code origin} are the inputs of the recomputed per-issue
 * {@code sourceSupport}, which (like the approvals) stays in the retained receipt and never reaches the snapshot. The bundle's
 * closed {@code impacts[]} (one row per S3 relation behind an INVOLVES edge: the producer's unverified proposal, the independent
 * verifier's per-quote effects as evidence ids and a recomputed label) is verified by {@link HandoffBundleVerifier} against the
 * edges, approvals and evidence but is deliberately NOT typed here: no import consumer needs it, so it stays in the retained
 * receipt only (the snapshot carries no impact, proposal, effect or label) and is read back from there by the evidence membership
 * gate. Each issue's closed {@code summary} (bundle {@code -7}: {@code not-requested}, a deterministic
 * {@code temporal-review-pending}/{@code input-too-large}, a job-coded {@code unavailable}, or an {@code available} multi-article
 * summary whose claims cite only the issue's own mention evidence) is recomputed by {@link HandoffIssueSummary} from the bundle's
 * mentions, verdicts, evidence and articles, but is deliberately NOT typed here either: the receipt keeps the exact producer
 * object and the snapshot never carries it. A reader that serves it must apply the current-rights and asOf gate to every
 * basis quote of the issue (the union of its mention evidence), not only to the cited ones.
 *
 * <p>{@code pathCompanies} are the PRIVATE support references of structural paths: the mapped middle companies of complete
 * two-hop paths that are not public {@code companies}. They are catalogue-validated beside {@code companies} but are never
 * public graph nodes, never written to the snapshot, and the structural path itself (and each basis's business and product
 * scope text) stays in the retained receipt: an operator-mapped basis chain, not a causality or price-direction claim.
 */
public record HandoffBundle(String handoffId, String manifestDigest, String sourceKind, String executionMode,
        String recordingKind, String policyVersion, Map<String, String> files, List<SourcePin> sources,
        List<Company> companies, List<Company> pathCompanies, List<Issue> issues, List<Relation> relations,
        List<Evidence> evidence, List<Article> articles, List<Approval> approvals) {

    public HandoffBundle {
        files = Map.copyOf(files);
        sources = List.copyOf(sources);
        companies = List.copyOf(companies);
        pathCompanies = List.copyOf(pathCompanies);
        issues = List.copyOf(issues);
        relations = List.copyOf(relations);
        evidence = List.copyOf(evidence);
        articles = List.copyOf(articles);
        approvals = List.copyOf(approvals);
    }

    /** One pinned S3 relation job with its S2 upstream, as the manifest and the bundle both list it. */
    public record SourcePin(String relationJobId, String relationInputDigest, String upstreamJobId,
            String upstreamInputDigest, String upstreamDigest, String reviewDigest) {
    }

    /** {@code id} is the public company id (it must equal {@code companies.id}). */
    public record Company(String id, String label) {
    }

    /**
     * @param title            becomes the issue label
     * @param eventTime        as the source states it, or {@code null} when an operator verdict withheld it (then the precision is
     *                         {@code unknown}); its precision is {@code timePrecision} (never widened)
     * @param assertionStatus  the producer's issue-level field; the snapshot carries it as given (null when not given)
     * @param geography        {@code domestic}/{@code international} by a field verdict, or explicit P3 unknown {@code null}
     */
    public record Issue(String id, String title, String action, String target, String eventTime, String timePrecision,
            String assertionStatus, String geography, String geographyPolicyVersion, List<String> geographyEvidenceIds,
            List<String> evidenceIds) {
        public Issue {
            geographyEvidenceIds = List.copyOf(geographyEvidenceIds);
            evidenceIds = List.copyOf(evidenceIds);
        }
    }

    /** {@code origin} is the provenance origin: {@code s3-relation}, {@code manual-operator-review} or an S2 comparison. */
    public record Relation(String id, String type, String source, String target, String role, String assertionStatus,
            List<String> evidenceIds, List<Basis> basis, String origin) {
        public Relation {
            evidenceIds = List.copyOf(evidenceIds);
            basis = List.copyOf(basis);
        }
    }

    /** {@code validFrom} is the first and {@code validUntil} the last valid day (inclusive); null means unknown, never "forever". */
    public record Basis(String verifiedAt, String validFrom, String validUntil) {
    }

    /**
     * One evidence span. {@code sourceEvidenceId} and {@code rawLocatorIds} are the S2-1 facts the importer re-derives from
     * the current export of the document.
     */
    public record Evidence(String id, String articleId, String articleVersion, int start, int end, String quoteSha256,
            List<String> rawLocatorIds, String documentId, String documentVersion, String rawVersion,
            String textArtifactId, String sourceEvidenceId) {
        public Evidence {
            rawLocatorIds = List.copyOf(rawLocatorIds);
        }
    }

    /** {@code precision} is {@code datetime} (an instant), {@code day} (a calendar date) or {@code unknown} (null). */
    public record Article(String articleId, String articleVersion, String documentId, String documentVersion,
            String rawVersion, String title, String url, String publishedAt, String precision,
            List<ObservationPin> observations, String textSha256, Origin origin) {
        public Article {
            observations = List.copyOf(observations);
        }
    }

    /**
     * The operator-declared origin of one document version ({@code verification: "operator-declared-origin"}); never inferred from
     * a publisher, a URL or a source id. {@code null} on the article means that no origin was declared (an unknown lineage).
     */
    public record Origin(String originId, String reviewer, String decisionRef, String decisionVersion) {
    }

    /**
     * The effective eligibility of one S3 relation the bundle's edges rest on: {@code kind} is {@code automatic-verifier} (the
     * independent verifier supported every claim; {@code reviewer} is null) or {@code operator-final-approval} (a human approved a
     * HOLD; this is not a verifier verdict). {@code revision} is the review revision the eligibility was decided at and
     * {@code decidedAt} the time of that deciding event.
     */
    public record Approval(String jobId, String relationCandidateId, String kind, int revision, String reviewer,
            String decidedAt) {
    }

    /** One recorded observation of the document: the exact S2-1 selector plus the grant it was exported under. */
    public record ObservationPin(String roundId, String sourceId, int page, int ordinal, String observedAt,
            String grantId, String grantRevision) {
    }
}
