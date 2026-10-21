package com.zoop.document.evidence.service;

import java.time.Clock;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Pattern;

import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;
import com.zoop.document.analysis.ExactReceiptProof;
import com.zoop.document.analysis.GrantRegistry;
import com.zoop.document.evidence.dto.EvidenceArticle;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.document.evidence.graph.GraphEvidenceReader;
import com.zoop.document.evidence.repository.AnalysisIdentity;
import com.zoop.document.evidence.repository.EvidenceReadRepository;
import com.zoop.document.evidence.repository.EvidenceView;
import com.zoop.document.evidence.repository.SummaryView;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.document.importer.SourceRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.JsonNode;

/**
 * {@code GET /api/v1/evidence/{id}}: one verified body citation, either of a stored S1 document summary or of a pinned public graph
 * version, always under the CURRENT document state and the CURRENT operator authority. It never calls a model or the AI service
 * and never writes (no database write, no file created, repaired or deleted, nothing activated). The rules are in
 * {@code api/docs/DOCUMENT_ANALYSIS.md} (S1) and {@code api/docs/GRAPH_READ_HANDOFF.md} (graph).
 *
 * <p>Which one it is follows from what is stored: a row verified by a graph import {@code verification_receipt} is a graph
 * citation, every other row an S1 citation. S1 citations have no pinned form, so a graph version or as-of is refused for them
 * ({@code VERSION_UNAVAILABLE}) before the S1 registry is read, and {@code eventIds} is a failed section. Graph citations are
 * answered from the version the shared selector pins, authorized by the S2-1 source registry and not by the S1 one. A withheld
 * citation is {@code EVIDENCE_UNAVAILABLE} without a reason on the wire; the reason is logged with the request id.
 */
public class EvidenceService {
    static final String SOURCE = "document-analysis";
    static final String EVENT_IDS = "eventIds";
    static final String SENTIMENT = "sentiment";
    static final String EVENT_IDS_MESSAGE = "그래프 저장소가 연결되지 않아 사건 연결을 확인하지 못했습니다.";
    static final String SENTIMENT_MESSAGE = "그래프 저장소가 연결되지 않아 기업 연결을 검증하지 못했습니다. 기업별 판정을 제공하지 않습니다.";
    static final String GRAPH_SOURCE = "public_graph_snapshot";
    static final String GRAPH_SENTIMENT_MESSAGE = "기업 연결은 이 근거 읽기에서 검증하지 않습니다. 기업별 판정을 제공하지 않습니다.";

    private static final Logger log = LoggerFactory.getLogger(EvidenceService.class);
    private static final Pattern EVIDENCE_ID = Pattern.compile("ev-[0-9a-f]{64}");
    private static final String SUMMARY_STAGE = "document-summary";
    private static final String VERIFIER_STAGE = "semantic-verification";
    private static final String AVAILABLE = "available";
    private static final String EXACT_RECEIPT = "exact_receipt";
    private static final String JSON_MEDIA_TYPE = "application/json";
    private static final String GRAPH_RECEIPT = "verification_receipt";
    private static final Set<String> SUMMARY_KEYS = Set.of("schemaVersion", "artifactId", "documentId", "documentVersion",
            "resultVersion", "text", "claims", "citations", "limitations", "producedAt", "provenance");
    private static final Set<String> CLAIM_KEYS = Set.of("claimId", "text", "assertionKind", "evidenceIds");
    private static final Set<String> CITATION_KEYS = Set.of("evidenceId", "documentId", "documentVersion", "textArtifactId",
            "offsetUnit", "start", "end", "quote", "inputKind", "rawLocatorIds");
    private static final Set<String> PROVENANCE_KEYS = Set.of("sourceKind", "executionMode", "recordingKind");

    private final EvidenceReadRepository evidence;
    private final DocumentRegistryRepository registry;
    private final DocumentReadGrants grants;
    private final DocumentReadSources sources;
    private final GraphEvidenceReader graph;
    private final EvidenceArtifactReader artifacts;
    private final Clock clock;
    private final TransactionOperations transaction;

    public EvidenceService(EvidenceReadRepository evidence, DocumentRegistryRepository registry, DocumentReadGrants grants,
            DocumentReadSources sources, GraphEvidenceReader graph, EvidenceArtifactReader artifacts, Clock clock,
            TransactionOperations transaction) {
        this.evidence = evidence;
        this.registry = registry;
        this.grants = grants;
        this.sources = sources;
        this.graph = graph;
        this.artifacts = artifacts;
        this.clock = clock;
        this.transaction = transaction;
    }

    /** A gate said no: the reason is a short token for the log, never for the client. */
    private static final class Denied extends RuntimeException {
        Denied(String reason) {
            super(reason, null, false, false);
        }
    }

    /** The job that created a cache-served analysis's artifacts and the analysis that owns that job. */
    private record Creator(String jobId, String analysisId) {
    }

    /** A stored citation of a summary result: identity and offsets, enough to find it in a receipt. */
    private record Cited(String evidenceId, long start, long end) {
    }

    public EvidenceResponse read(String id, String round, String graphVersion, String asOf, String companyId,
            String requestId) {
        for (String value : new String[] {round, graphVersion, asOf, companyId}) {
            if (value != null && value.isBlank()) {
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            }
        }
        Instant requestedAsOf = null;
        if (asOf != null) {
            try {
                requestedAsOf = OffsetDateTime.parse(asOf).toInstant();
            } catch (DateTimeException error) {
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            }
        }
        if (round != null) {
            // Briefing rounds pin no graph version yet: refused for every kind of evidence, before any lookup.
            throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
        }
        if (!EVIDENCE_ID.matcher(id).matches()) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }
        Instant now = clock.instant();
        Instant pinnedAt = requestedAsOf;
        try {
            return transaction.execute(status -> dispatch(id, graphVersion, pinnedAt, companyId, requestId, now, false));
        } catch (DataAccessException | TransactionException error) {
            log.warn("Evidence read failed in the database (cause={}, requestId={})", error.getClass().getSimpleName(), requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, error);
        }
    }

    /**
     * The registry is chosen by what is STORED, never by a request parameter: a row whose verification artifact is a graph
     * import {@code verification_receipt} is a graph body citation; every other row is an S1 summary citation. S1 citations
     * have no pinned form: a graph version or as-of is refused before the S1 registry is read.
     */
    private EvidenceResponse dispatch(String id, String graphVersion, Instant asOf, String companyId, String requestId,
            Instant now, boolean pinGraphOnly) {
        EvidenceView row = evidence.findEvidence(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        ArtifactRow verification = row.verificationArtifactId() == null ? null
                : registry.findArtifact(row.verificationArtifactId()).orElse(null);
        if (verification != null && GRAPH_RECEIPT.equals(verification.kind())) {
            return serveGraph(row, graphVersion, asOf, companyId, requestId, now);
        }
        if (!pinGraphOnly && (graphVersion != null || asOf != null)) {
            throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
        }
        return serve(row, companyId, requestId, now, grants.registry(requestId));
    }

    /**
     * Whether a citation is readable right now under exactly the gates of {@link #read}, for stored chat results that must be
     * re-checked every time they are returned: a graph citation at the given pinned version and as-of, an S1 citation
     * unpinned (it has no pinned form). A denial, an unknown id and an unverifiable state (registry or store unreadable) are
     * all "not readable"; denials are logged with the request id as in a read. It never writes.
     */
    public boolean readable(String id, String graphVersion, Instant asOf, String requestId) {
        return readability(id, graphVersion, asOf, requestId) == Readability.READABLE;
    }

    /** What {@link #readable} decides, keeping a denial apart from a state that could not be checked. */
    public enum Readability { READABLE, DENIED, UNAVAILABLE }

    /**
     * {@link #readable} for a caller that must not mistake an outage for an absence (a chat tool that reports what it found):
     * an unknown id, a denial or an unverified span is {@code DENIED}; an unreadable registry, store, version or database is
     * {@code UNAVAILABLE}.
     */
    public Readability readability(String id, String graphVersion, Instant asOf, String requestId) {
        if (id == null || !EVIDENCE_ID.matcher(id).matches()) {
            return Readability.DENIED;
        }
        Instant now = clock.instant();
        try {
            transaction.execute(status -> dispatch(id, graphVersion, asOf, null, requestId, now, true));
            return Readability.READABLE;
        } catch (CustomException notReadable) {
            return switch (notReadable.getErrorCode()) {
                case RESOURCE_NOT_FOUND, EVIDENCE_UNAVAILABLE, INVALID_REQUEST -> Readability.DENIED;
                default -> Readability.UNAVAILABLE;
            };
        } catch (DataAccessException | TransactionException unavailable) {
            return Readability.UNAVAILABLE;
        }
    }

    private EvidenceResponse serve(EvidenceView row, String companyId, String requestId, Instant now, GrantRegistry current) {
        String id = row.id();
        ArticleRow article;
        VersionRow version;
        SummaryView owner;
        JsonNode ownerResult;
        try {
            if (!"body".equals(row.inputKind()) || !Boolean.TRUE.equals(row.quoteVerified())
                    || row.verificationArtifactId() == null) {
                throw new Denied("not_verified_body_evidence");
            }
            List<SummaryView> owners = evidence.findSummariesByExactReceipt(row.verificationArtifactId());
            if (owners.size() != 1) {
                throw new Denied(owners.isEmpty() ? "owner_missing" : "owner_ambiguous");
            }
            owner = owners.get(0);
            if (!"summary".equals(owner.stage()) || !AVAILABLE.equals(owner.status()) || owner.companyId() != null
                    || !row.articleId().equals(owner.articleId()) || !row.articleVersion().equals(owner.articleVersion())
                    || !("exact-" + owner.id()).equals(row.verificationArtifactId())) {
                throw new Denied("owner_invalid");
            }
            article = registry.findArticle(row.articleId()).orElseThrow(() -> new Denied("article_missing"));
            if (!AVAILABLE.equals(article.accessStatus())) {
                throw new Denied("article_access_" + article.accessStatus());
            }
            if (!row.articleVersion().equals(article.currentVersion())) {
                throw new Denied("version_not_current");
            }
            version = registry.findVersion(row.articleId(), row.articleVersion())
                    .orElseThrow(() -> new Denied("version_missing"));
            if (!row.textArtifactId().equals(version.textArtifactId())) {
                throw new Denied("text_artifact_mismatch");
            }
            if (row.startOffset() < 0 || row.endOffset() <= row.startOffset()
                    || row.quote().codePointCount(0, row.quote().length()) != row.endOffset() - row.startOffset()) {
                throw new Denied("quote_offsets_inconsistent");
            }
            ownerResult = storedSummary(owner, version, requestId);
            if (!cites(ownerResult, row)) {
                throw new Denied("owner_result_does_not_cite_evidence");
            }
            authorize(owner, new Cited(row.id(), row.startOffset(), row.endOffset()), article, version, current, now, requestId);
        } catch (Denied denied) {
            log.info("Evidence withheld (evidenceId={}, reason={}, requestId={})", id, denied.getMessage(), requestId);
            throw new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE);
        }
        if (companyId != null && !evidence.companyExists(companyId)) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }

        JsonNode summary = null;
        String resultVersion = null;
        SummaryView latest = evidence.latestSummary(row.articleId(), row.articleVersion()).orElse(null);
        if (latest != null && AVAILABLE.equals(latest.status())) {
            JsonNode latestResult = latest.id().equals(owner.id()) ? ownerResult : storedSummary(latest, version, requestId);
            boolean allowed = true;
            if (!latest.id().equals(owner.id())) {
                try {
                    if (!("exact-" + latest.id()).equals(latest.exactReceiptId())) {
                        throw new Denied("latest_exact_receipt_invalid");
                    }
                    authorize(latest, firstCitation(latestResult), article, version, current, now, requestId);
                } catch (Denied denied) {
                    log.info("Latest summary withheld (evidenceId={}, analysisId={}, reason={}, requestId={})", id, latest.id(),
                            denied.getMessage(), requestId);
                    allowed = false;
                }
            }
            if (allowed) {
                summary = latestResult;
                resultVersion = latest.resultVersion();
            }
        }

        List<SectionFailure> failures = new ArrayList<>();
        failures.add(new SectionFailure(EVENT_IDS, ErrorCode.SOURCE_UNAVAILABLE.name(), EVENT_IDS_MESSAGE, false, null));
        if (companyId != null) {
            failures.add(new SectionFailure(SENTIMENT, ErrorCode.SOURCE_UNAVAILABLE.name(), SENTIMENT_MESSAGE, false, null));
        }
        EvidenceArticle articleOut = new EvidenceArticle(version.title(), version.publisher(), version.url(),
                "datetime".equals(version.publicationPrecision()) ? version.publishedAt() : null);
        return new EvidenceResponse(row.id(), row.quote(), row.startOffset(), row.endOffset(), row.articleId(),
                row.articleVersion(), articleOut, Boolean.TRUE, List.of(),
                new Metadata(SOURCE, now, null, requestId, true, List.copyOf(failures)), null, row.articleVersion(), summary,
                null, summary == null ? null : summary.get("provenance"), resultVersion);
    }

    // ---- graph body evidence ---------------------------------------------------------------------------------------------

    /**
     * One verified body citation of a pinned public graph version. The pinned, filtered snapshot decides visibility and the span;
     * the app's own article rows decide that the quote is still readable (access, selected version, stored text); the selected
     * version's own import receipt, verified against its registered hash and size and read ONCE, names the grants the version was
     * imported under (and, for a span no visible issue or relation cites but a visible structural basis references, proves that
     * exactly that relation's basis cites it: such a basis-only citation has no {@code eventIds}); and the CURRENT S2-1 source
     * registry, read now, decides whether those grants still allow it. The receipt grants nothing and the S1 registry is not
     * involved. Any denial is {@code EVIDENCE_UNAVAILABLE} without a reason on the wire.
     */
    private EvidenceResponse serveGraph(EvidenceView row, String graphVersion, Instant asOf, String companyId, String requestId,
            Instant now) {
        // A selector failure keeps its own status: 409 unavailable or staged, 422 inconsistent, 503 unreadable snapshot.
        GraphEvidence found = graph.read(graphVersion, asOf, row.id());
        ArticleRow article;
        VersionRow version;
        try {
            GraphEvidence.Span span = found.span();
            if (span == null) {
                throw new Denied("evidence_not_visible_in_version");
            }
            if (!"body".equals(row.inputKind()) || !Boolean.TRUE.equals(row.quoteVerified())) {
                throw new Denied("not_verified_body_evidence");
            }
            if (!span.articleId().equals(row.articleId()) || !span.articleVersion().equals(row.articleVersion())
                    || span.start() != row.startOffset() || span.end() != row.endOffset()) {
                throw new Denied("span_mismatch");
            }
            article = registry.findArticle(row.articleId()).orElseThrow(() -> new Denied("article_missing"));
            if (!AVAILABLE.equals(article.accessStatus())) {
                throw new Denied("article_access_" + article.accessStatus());
            }
            // The version is pinned by the snapshot, so it is not required to be the article's newest one.
            version = registry.findVersion(row.articleId(), row.articleVersion())
                    .orElseThrow(() -> new Denied("version_missing"));
            if (!row.textArtifactId().equals(version.textArtifactId())) {
                throw new Denied("text_artifact_mismatch");
            }
            if (row.startOffset() < 0 || row.endOffset() <= row.startOffset()
                    || row.quote().codePointCount(0, row.quote().length()) != row.endOffset() - row.startOffset()) {
                throw new Denied("quote_offsets_inconsistent");
            }
            // The receipt of the SELECTED version, not the row's own: a row shared by several imports points at the first one. Its
            // bytes are read and parsed once for the grant pins and, for a basis-only span, for the basis membership.
            StrictJson.Obj receiptBundle = GraphReceiptGrants.bundle(receipt(found.graphVersion(), requestId), found.graphVersion());
            Set<GraphReceiptGrants.Pin> pins = GraphReceiptGrants.pins(receiptBundle, row.articleId(), row.articleVersion());
            if (!found.basisRefs().isEmpty()) {
                GraphReceiptBasis.require(receiptBundle, row.id(), found.basisRefs());
            }
            for (GraphReceiptGrants.Pin pin : pins) {
                if (!pin.sourceId().equals(article.provider())) {
                    throw new Denied("pin_source_differs_from_article_provider");
                }
            }
            SourceRegistry current = sources.registry(requestId);
            for (GraphReceiptGrants.Pin pin : pins) {
                String denial = current.denial(pin.sourceId(), pin.grantId(), pin.revision(), now);
                if (denial != null) {
                    throw new Denied("source_" + denial);
                }
            }
        } catch (GraphReceiptGrants.Malformed malformed) {
            log.info("Graph evidence withheld (evidenceId={}, reason={}, requestId={})", row.id(), malformed.getMessage(), requestId);
            throw new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE);
        } catch (Denied denied) {
            log.info("Graph evidence withheld (evidenceId={}, reason={}, requestId={})", row.id(), denied.getMessage(), requestId);
            throw new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE);
        }
        if (companyId != null && !evidence.companyExists(companyId)) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }

        List<SectionFailure> failures = companyId == null ? List.of()
                : List.of(new SectionFailure(SENTIMENT, ErrorCode.SOURCE_UNAVAILABLE.name(), GRAPH_SENTIMENT_MESSAGE, false, null));
        EvidenceArticle articleOut = new EvidenceArticle(version.title(), version.publisher(), version.url(),
                "datetime".equals(version.publicationPrecision()) ? version.publishedAt() : null);
        return new EvidenceResponse(row.id(), row.quote(), row.startOffset(), row.endOffset(), row.articleId(),
                row.articleVersion(), articleOut, Boolean.TRUE, found.eventIds(),
                new Metadata(GRAPH_SOURCE, found.asOf(), found.graphVersion(), requestId, companyId != null, failures), null,
                row.articleVersion(), null, null, null, null);
    }

    /**
     * The verified bytes of the selected version's import receipt. A registry mismatch (missing, wrong kind, changed file) is a
     * denial; an unset artifact root or an unreadable store is {@code SOURCE_UNAVAILABLE}, never a denial that reads like absence.
     */
    private byte[] receipt(String versionId, String requestId) {
        ArtifactRow receipt = registry.findArtifact("artifact-receipt-" + versionId)
                .orElseThrow(() -> new Denied("receipt_unregistered"));
        if (!GRAPH_RECEIPT.equals(receipt.kind()) || !JSON_MEDIA_TYPE.equals(receipt.mediaType())) {
            throw new Denied("receipt_kind_invalid");
        }
        try {
            return artifacts.read(receipt);
        } catch (ArtifactStoreException error) {
            if (error.reason() == ArtifactStoreException.Reason.CONFLICT) {
                throw new Denied("receipt_file_" + error.detail());
            }
            log.warn("Graph receipt cannot be read (artifactId={}, reason={}, detail={}, requestId={})", receipt.id(),
                    error.reason(), error.detail(), requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    // ---- current authority ------------------------------------------------------------------------------------------------

    /**
     * Throws {@link Denied} unless the CURRENT registry still covers the analysis: the grant snapshot it was settled under
     * (revision, source, expiry, operations, purposes) and the recipients its own receipts prove. A database or storage failure
     * is {@code SOURCE_UNAVAILABLE}, never a denial that reads like "no evidence".
     */
    private void authorize(SummaryView analysis, Cited cited, ArticleRow article, VersionRow version, GrantRegistry current,
            Instant now, String requestId) {
        if (analysis.grantReference() == null || analysis.grantRevision() == null || analysis.aiJobId() == null
                || analysis.resultVersion() == null || analysis.resultArtifactId() == null
                || analysis.semanticReceiptId() == null) {
            throw new Denied("analysis_incomplete");
        }
        // One settlement per analysis, and the calls of a cache-served result are recorded under the job that created them.
        // So an analysis with executions of its own made its calls itself; otherwise only its exact receipt file names the creator.
        Creator creator = evidence.executionsExist(analysis.aiJobId())
                ? new Creator(analysis.aiJobId(), analysis.id())
                : cachedCreator(analysis, cited, version, requestId);
        Map<String, Set<String>> byStage = evidence.executionRecipients(creator.jobId(), creator.analysisId(),
                analysis.grantReference(), analysis.grantRevision());
        Set<String> generation = byStage.get(SUMMARY_STAGE);
        Set<String> verifier = byStage.get(VERIFIER_STAGE);
        if (generation == null || generation.isEmpty() || verifier == null || verifier.isEmpty()) {
            throw new Denied("recipient_unproven");
        }
        Set<String> union = new TreeSet<>();
        for (Set<String> stage : List.of(generation, verifier)) {
            for (String recipient : stage) {
                if (recipient == null) {
                    throw new Denied("recipient_unproven");
                }
                union.add(recipient);
            }
        }
        String denial = GrantRegistry.evaluate(current.current(analysis.grantReference()).orElse(null), article.provider(),
                analysis.grantRevision(), GrantRegistry.purposesOf(SUMMARY_STAGE), List.copyOf(union), true, now);
        if (denial != null) {
            throw new Denied(denial);
        }
    }

    /**
     * The creator of a cache-served analysis, proven by ONE verified read of the analysis's own exact receipt: the file must
     * match the registry's hash and size, name this analysis, document, text, result and citation, and reproduce both
     * content-addressed artifact ids from its creator job and input digest. The creator must be another analysis of the same
     * document version and scope. Its status and result are not read: it is source-level context, not a publication claim.
     */
    private Creator cachedCreator(SummaryView analysis, Cited cited, VersionRow version, String requestId) {
        if (!("exact-" + analysis.id()).equals(analysis.exactReceiptId())) {
            throw new Denied("exact_receipt_id_invalid");
        }
        ArtifactRow receipt = registry.findArtifact(analysis.exactReceiptId()).orElseThrow(() -> new Denied("exact_receipt_unregistered"));
        if (!EXACT_RECEIPT.equals(receipt.kind()) || !JSON_MEDIA_TYPE.equals(receipt.mediaType())) {
            throw new Denied("exact_receipt_kind_invalid");
        }
        ArtifactRow text = registry.findArtifact(version.textArtifactId()).orElseThrow(() -> new Denied("text_unregistered"));
        byte[] content;
        try {
            content = artifacts.read(receipt);
        } catch (ArtifactStoreException error) {
            if (error.reason() == ArtifactStoreException.Reason.CONFLICT) {
                throw new Denied("exact_receipt_file_" + error.detail());
            }
            log.warn("Exact receipt cannot be read (artifactId={}, reason={}, detail={}, requestId={})", receipt.id(),
                    error.reason(), error.detail(), requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        String creatorJob = ExactReceiptProof.creatorJobId(content, new ExactReceiptProof.Subject(analysis.id(),
                analysis.aiJobId(), analysis.articleId(), analysis.articleVersion(), version.textArtifactId(), text.sha256(),
                analysis.resultVersion(), analysis.resultArtifactId(), analysis.semanticReceiptId(), cited.evidenceId(),
                cited.start(), cited.end()));
        if (creatorJob == null) {
            throw new Denied("exact_receipt_mismatch");
        }
        AnalysisIdentity creator = evidence.findAnalysisByAiJobId(creatorJob).orElseThrow(() -> new Denied("creator_unknown"));
        if (creator.id().equals(analysis.id()) || !analysis.articleId().equals(creator.articleId())
                || !analysis.articleVersion().equals(creator.articleVersion()) || !"summary".equals(creator.stage())
                || creator.companyId() != null) {
            throw new Denied("creator_out_of_scope");
        }
        return new Creator(creatorJob, creator.id());
    }

    // ---- stored result ----------------------------------------------------------------------------------------------------

    /**
     * The analysis's stored result as the one body that may be served. It is parsed strictly and must be exactly the
     * {@code DocumentAnalysisSummary} shape of this document version and result; anything else is a stored-data failure
     * (500), never a partial body and never another result.
     */
    private JsonNode storedSummary(SummaryView analysis, VersionRow version, String requestId) {
        try {
            if (analysis.resultJson() == null) {
                throw new StrictJson.Malformed();
            }
            StrictJson.Obj result = StrictJson.parseObject(analysis.resultJson()).exactly(SUMMARY_KEYS);
            if (!GrantRegistry.SCHEMA.equals(result.string("schemaVersion"))
                    || !analysis.resultArtifactId().equals(result.string("artifactId"))
                    || !analysis.articleId().equals(result.string("documentId"))
                    || !analysis.articleVersion().equals(result.string("documentVersion"))
                    || !analysis.resultVersion().equals(result.string("resultVersion"))) {
                throw new StrictJson.Malformed();
            }
            for (StrictJson.Obj claim : result.objects("claims")) {
                claim.exactly(CLAIM_KEYS);
                claim.string("claimId");
                claim.string("text");
                String assertionKind = claim.string("assertionKind");
                if (!"fact".equals(assertionKind) && !"interpretation".equals(assertionKind)
                        && !"limitation".equals(assertionKind)) {
                    throw new StrictJson.Malformed();
                }
                claim.strings("evidenceIds");
            }
            result.strings("limitations");
            result.string("producedAt");
            StrictJson.Obj provenance = result.object("provenance").exactly(PROVENANCE_KEYS);
            for (String key : PROVENANCE_KEYS) {
                provenance.string(key);
            }
            for (StrictJson.Obj citation : result.objects("citations")) {
                citation.exactly(CITATION_KEYS);
                if (!"unicode_code_point".equals(citation.string("offsetUnit"))
                        || !analysis.articleId().equals(citation.string("documentId"))
                        || !analysis.articleVersion().equals(citation.string("documentVersion"))
                        || !version.textArtifactId().equals(citation.string("textArtifactId"))) {
                    throw new StrictJson.Malformed();
                }
                citation.string("evidenceId");
                citation.string("quote");
                citation.string("inputKind");
                citation.count("start");
                citation.count("end");
                citation.strings("rawLocatorIds");
            }
            return result.node();
        } catch (StrictJson.Malformed malformed) {
            log.error("Stored summary result is not servable (analysisId={}, requestId={})", analysis.id(), requestId);
            throw new CustomException(ErrorCode.INTERNAL_ERROR);
        }
    }

    /** Whether the validated result of the owner cites exactly this evidence row (id, text, offsets and quote). */
    private static boolean cites(JsonNode result, EvidenceView row) {
        int matches = 0;
        for (JsonNode citation : result.get("citations").values()) {
            if (!row.id().equals(citation.get("evidenceId").stringValue())) {
                continue;
            }
            matches++;
            if (!row.textArtifactId().equals(citation.get("textArtifactId").stringValue())
                    || citation.get("start").longValue() != row.startOffset() || citation.get("end").longValue() != row.endOffset()
                    || !row.quote().equals(citation.get("quote").stringValue())
                    || !row.inputKind().equals(citation.get("inputKind").stringValue())) {
                return false;
            }
        }
        return matches == 1;
    }

    /** Any one citation of a validated result: enough to find the analysis's own entry in its exact receipt. */
    private static Cited firstCitation(JsonNode result) {
        for (JsonNode citation : result.get("citations").values()) {
            return new Cited(citation.get("evidenceId").stringValue(), citation.get("start").longValue(),
                    citation.get("end").longValue());
        }
        throw new Denied("no_citation");
    }
}
