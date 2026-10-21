package com.zoop.graph.importer;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import com.zoop.document.analysis.repository.EvidenceRow;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.IngestionExporter;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.importer.GraphHandoffRepository.CompanyRow;
import com.zoop.graph.importer.GraphHandoffRepository.NewStagedVersion;
import com.zoop.graph.importer.GraphHandoffRepository.StagedVersion;
import com.zoop.graph.importer.GraphHandoffRepository.StoredEvidence;
import com.zoop.graph.importer.GraphHandoffResult.Outcome;
import com.zoop.graph.importer.GraphHandoffResult.Staged;
import com.zoop.graph.importer.GraphHandoffResult.StoredFileFact;
import com.zoop.graph.importer.HandoffBundle.Article;
import com.zoop.graph.importer.HandoffBundle.Company;
import com.zoop.graph.importer.HandoffBundle.Evidence;
import com.zoop.graph.importer.HandoffBundle.Relation;
import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;
import com.zoop.graph.importer.HandoffObservationVerifier.ObservationFacts;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.GraphSnapshotUnavailableException;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionOperations;

/**
 * Stages one AI handoff as an INACTIVE graph version, in this order:
 * <ol>
 * <li>the current export of the handoff ({@code zoop-ai-handoff export}) is parsed, pinned to the digests of the request and
 *     validated in full;</li>
 * <li>every observation the bundle records is exported again through {@code zoop-ai-ingest export --require-store}, so the
 *     current rights and the source facts decide, not the bundle's grant fields;</li>
 * <li>one database transaction takes the company catalog lock first, then verifies the app side (article versions, text,
 *     companies), writes the immutable snapshot and receipt files, registers the artifacts, the evidence rows and the version
 *     row, and then repeats step 1 and 2: if rights or source facts changed in the meantime the transaction is rolled back
 *     instead of committed.</li>
 * </ol>
 * The run holds the operator lock of the artifact store, which is the lock of the document import and analysis. It can only
 * add rows: it never writes {@code graph_activations}, never sets {@code graph_versions.active} (it does not take the
 * publication lock, because it cannot move the pointer) and never changes an article's current version. A version staged here is
 * unreadable through the public API until a separate activation exists.
 *
 * <p>Catalog lock: the company names, and that no company has the id of an issue, are read once and are only true at the commit
 * when no catalog write can land in between. The transaction therefore starts with {@link GraphHandoffRepository#lockCatalog()}
 * and keeps the lock to the commit. The catalog import takes its own table lock before anything else too, so neither waits on
 * the other while holding what the other needs: a writer that comes later waits for this commit, and one that holds the lock
 * first makes this import wait and then read the committed catalog. Like the catalog import and the article row locks, the
 * wait has no timeout of its own; it ends with the other transaction, or as a database error ({@code database_unavailable}).
 *
 * <p>A file this run created is removed again only when the transaction is known to have rolled back; when the database outcome
 * is unknown the file stays, because the rows may have committed, and the next import of the same pins adopts it after the byte
 * comparison. A file that already existed is never removed.
 */
public final class GraphHandoffImporter {
    static final String SNAPSHOT_DIRECTORY = "graph_snapshot";
    static final String RECEIPT_DIRECTORY = "verification_receipt";
    static final String SNAPSHOT_KIND = "graph_snapshot";
    static final String RECEIPT_KIND = "verification_receipt";
    static final String REASON = "operator handoff import: staged, not activated";
    private static final String JSON_MEDIA_TYPE = "application/json";
    private static final String AVAILABLE = "available";
    private static final Logger log = LoggerFactory.getLogger(GraphHandoffImporter.class);

    private final HandoffExporter handoffExporter;
    private final HandoffExportParser handoffParser;
    private final HandoffObservationVerifier observations;
    private final ArtifactFileStore store;
    private final DocumentRegistryRepository registry;
    private final GraphHandoffRepository graph;
    private final TransactionOperations transaction;
    private final Clock clock;

    public GraphHandoffImporter(HandoffExporter handoffExporter, IngestionExporter ingestionExporter,
            IngestionExportParser ingestionParser, ArtifactFileStore store, DocumentRegistryRepository registry,
            GraphHandoffRepository graph, TransactionOperations transaction, Clock clock) {
        this.handoffExporter = handoffExporter;
        this.handoffParser = new HandoffExportParser();
        this.observations = new HandoffObservationVerifier(ingestionExporter, ingestionParser);
        this.store = store;
        this.registry = registry;
        this.graph = graph;
        this.transaction = transaction;
        this.clock = clock;
    }

    /** The verified handoff, the facts of every observation and the facts keyed by article (first observation). */
    private record Checked(VerifiedHandoff handoff, List<ObservationFacts> facts, Map<String, ObservationFacts> byArticle) {
    }

    public GraphHandoffResult run(GraphHandoffRequest request) {
        ArtifactFileStore.Session session;
        try {
            session = store.open();
        } catch (ArtifactStoreException error) {
            log.warn("graph handoff import did not start: {} ({})", error.reason(), error.detail());
            return GraphHandoffResult.failed(new GraphHandoffException(error.reason() == ArtifactStoreException.Reason.BUSY
                    ? GraphHandoffFailure.IMPORT_BUSY : GraphHandoffFailure.ARTIFACT_STORE_UNAVAILABLE));
        }
        try (session) {
            return GraphHandoffResult.succeeded(stage(session, request));
        } catch (GraphHandoffException failure) {
            log.warn("graph handoff import failed: {}", failure.failure().code());
            return GraphHandoffResult.failed(failure);
        } catch (RuntimeException unexpected) {
            // State is unknown: keep any file (recoverable) and report without the exception's text.
            log.error("graph handoff import failed unexpectedly: {}", unexpected.getClass().getName());
            return GraphHandoffResult.failed(new GraphHandoffException(GraphHandoffFailure.INTERNAL_ERROR));
        }
    }

    private Staged stage(ArtifactFileStore.Session session, GraphHandoffRequest request) {
        Checked checked = check(request);
        String versionId = HandoffSnapshotWriter.versionId(request.handoffId());
        byte[] receiptBytes = receiptBytes(checked.handoff());
        List<ArtifactFileStore.StoredFile> created = new ArrayList<>();
        try {
            return transaction.execute(status -> write(session, request, checked, versionId, receiptBytes, created));
        } catch (GraphHandoffException rolledBack) {
            for (ArtifactFileStore.StoredFile file : created) {
                if (session.discard(file)) {
                    log.info("graph handoff import removed a file it had created");
                }
            }
            throw rolledBack;
        } catch (DataAccessException | TransactionException unknownOutcome) {
            log.error("graph handoff import database failure: {}", unknownOutcome.getClass().getSimpleName());
            throw new GraphHandoffException(GraphHandoffFailure.DATABASE_UNAVAILABLE);
        }
    }

    /** One complete check: the current handoff, then the current rights and source facts of every observation. */
    private Checked check(GraphHandoffRequest request) {
        VerifiedHandoff handoff = handoffParser.parse(handoffExporter.export(request.handoffId()), request);
        List<ObservationFacts> facts = observations.collect(handoff.bundle());
        return new Checked(handoff, facts, HandoffObservationVerifier.byArticle(handoff.bundle(), facts));
    }

    /** Repeats {@link #check} immediately before the commit; any difference means authority moved after the first look. */
    private void recheck(GraphHandoffRequest request, Checked first) {
        Checked second = check(request);
        if (!second.handoff().manifestDigest().equals(first.handoff().manifestDigest())
                || !second.handoff().bundleDigest().equals(first.handoff().bundleDigest())
                || !second.facts().equals(first.facts())) {
            throw new GraphHandoffException(GraphHandoffFailure.RIGHTS_CHANGED);
        }
    }

    private static byte[] receiptBytes(VerifiedHandoff handoff) {
        try {
            return HandoffSnapshotWriter.receipt(handoff);
        } catch (StrictJson.Malformed malformed) {
            throw new GraphHandoffException(GraphHandoffFailure.HANDOFF_EXPORT_INVALID);
        }
    }

    // ---------------------------------------------------------------------------------------------- the transaction ------

    private Staged write(ArtifactFileStore.Session session, GraphHandoffRequest request, Checked checked, String versionId,
            byte[] receiptBytes, List<ArtifactFileStore.StoredFile> created) {
        try {
            return writeChecked(session, request, checked, versionId, receiptBytes, created);
        } catch (DataAccessException failure) {
            // Known rollback: the statement failed inside this transaction (a commit failure is caught by the caller).
            log.error("graph handoff import database failure: {}", failure.getClass().getSimpleName());
            throw new GraphHandoffException(GraphHandoffFailure.DATABASE_UNAVAILABLE);
        }
    }

    private Staged writeChecked(ArtifactFileStore.Session session, GraphHandoffRequest request, Checked checked,
            String versionId, byte[] receiptBytes, List<ArtifactFileStore.StoredFile> created) {
        // First statement of the transaction: the catalog table lock comes before every row lock (articles) and every read of the
        // catalog (verifyApp), the order of the catalog import, and holds until the commit.
        graph.lockCatalog();
        HandoffBundle bundle = checked.handoff().bundle();
        Instant now = clock.instant();
        String snapshotArtifactId = "artifact-" + versionId;
        String receiptArtifactId = "artifact-receipt-" + versionId;
        String receiptSha256 = ArtifactFileStore.sha256(receiptBytes);

        Optional<StagedVersion> staged = graph.findVersion(versionId);
        if (staged.isPresent()) {
            ownsVersion(staged.get(), snapshotArtifactId, receiptArtifactId, receiptSha256, receiptBytes.length);
        }
        AppFacts app = verifyApp(session, bundle, checked, receiptArtifactId, now);
        if (staged.isPresent()) {
            return unchanged(session, request, checked, app, snapshotArtifactId, receiptArtifactId);
        }

        byte[] snapshotBytes = snapshotBytes(versionId, checked.handoff());
        if (snapshotBytes.length > ArtifactFileStore.MAX_READ_BYTES || receiptBytes.length > ArtifactFileStore.MAX_READ_BYTES) {
            throw new GraphHandoffException(GraphHandoffFailure.SNAPSHOT_INVALID);
        }
        ArtifactFileStore.StoredFile snapshotFile = put(session, created, SNAPSHOT_DIRECTORY, versionId + ".json", snapshotBytes);
        ArtifactFileStore.StoredFile receiptFile = put(session, created, RECEIPT_DIRECTORY, versionId + ".json", receiptBytes);
        registerArtifact(new ArtifactRow(snapshotArtifactId, SNAPSHOT_KIND, snapshotFile.uri(), snapshotFile.sha256(),
                snapshotFile.bytes(), JSON_MEDIA_TYPE, now));
        registerArtifact(new ArtifactRow(receiptArtifactId, RECEIPT_KIND, receiptFile.uri(), receiptFile.sha256(),
                receiptFile.bytes(), JSON_MEDIA_TYPE, now));
        int[] counts = registerEvidence(app.evidence(), true);
        graph.insertStagedVersion(new NewStagedVersion(versionId, "operator:" + request.operator(), REASON,
                "graph-handoff:" + bundle.handoffId(), bundle.policyVersion(), snapshotArtifactId, bundle.issues().size(),
                bundle.relations().size(), bundle.articles().size(), now));
        // The last word before the commit: the same checks, run again. A change rolls everything above back. The article rows are
        // still locked (verifyApp took them FOR UPDATE), so no withdrawal can slip in between this look and the commit.
        recheck(request, checked);
        revalidateArticles(bundle);
        return result(Outcome.STAGED, checked, bundle, counts, fact(snapshotArtifactId, snapshotFile),
                fact(receiptArtifactId, receiptFile));
    }

    /**
     * An existing row with this id is the same import only when it is a {@code snapshot} version whose receipt artifact is
     * byte-identical to the one these pins produce (the receipt holds the complete manifest and bundle, so equal receipts are
     * equal pins). Anything else is another import under the same handoff id: refused, never merged or overwritten.
     */
    private void ownsVersion(StagedVersion version, String snapshotArtifactId, String receiptArtifactId, String receiptSha256,
            long receiptBytes) {
        ArtifactRow receipt = registry.findArtifact(receiptArtifactId).orElse(null);
        if (!"snapshot".equals(version.kind()) || !snapshotArtifactId.equals(version.snapshotArtifactId())
                || receipt == null || !RECEIPT_KIND.equals(receipt.kind()) || !receipt.sha256().equals(receiptSha256)
                || receipt.bytes() != receiptBytes) {
            throw new GraphHandoffException(GraphHandoffFailure.VERSION_CONFLICT);
        }
    }

    /**
     * Identical pins, already staged: nothing is written. The registered snapshot and receipt files must still be intact (hash and
     * size), the snapshot must be this handoff's, and every evidence row must exist exactly as the bundle's spans produce it.
     */
    private Staged unchanged(ArtifactFileStore.Session session, GraphHandoffRequest request, Checked checked, AppFacts app,
            String snapshotArtifactId, String receiptArtifactId) {
        HandoffBundle bundle = checked.handoff().bundle();
        ArtifactRow snapshot = registry.findArtifact(snapshotArtifactId).orElseThrow(
                () -> new GraphHandoffException(GraphHandoffFailure.VERSION_CONFLICT));
        ArtifactRow receipt = registry.findArtifact(receiptArtifactId).orElseThrow(
                () -> new GraphHandoffException(GraphHandoffFailure.VERSION_CONFLICT));
        byte[] snapshotBytes = readRegistered(session, snapshot);
        readRegistered(session, receipt);
        PublicGraphSnapshot stored;
        try {
            stored = GraphSnapshotCodec.read(snapshotBytes, HandoffSnapshotWriter.versionId(request.handoffId()));
        } catch (GraphSnapshotUnavailableException invalid) {
            throw new GraphHandoffException(GraphHandoffFailure.VERSION_CONFLICT);
        }
        if (!request.handoffId().equals(stored.sourceBundleId()) || stored.issues().size() != bundle.issues().size()
                || stored.relations().size() != bundle.relations().size() || stored.articles().size() != bundle.articles().size()
                || stored.evidence().size() != bundle.evidence().size()) {
            throw new GraphHandoffException(GraphHandoffFailure.VERSION_CONFLICT);
        }
        int[] counts = registerEvidence(app.evidence(), false);
        return result(Outcome.UNCHANGED, checked, bundle, counts, new StoredFileFact(snapshotArtifactId, snapshot.sha256(),
                snapshot.bytes(), "existing"), new StoredFileFact(receiptArtifactId, receipt.sha256(), receipt.bytes(), "existing"));
    }

    // ---------------------------------------------------------------------------------------------- app verification -----

    /** What the app side proved: the evidence rows to register, with their exact quotes. */
    private record AppFacts(List<EvidenceRow> evidence) {
    }

    private AppFacts verifyApp(ArtifactFileStore.Session session, HandoffBundle bundle, Checked checked,
            String receiptArtifactId, Instant now) {
        // The catalogue is checked for the UNION of the public companies and the private path companies: both must exist with an
        // equal label. A path company is never a graph node; it only has to be a real catalogue company, under the same lock.
        List<Company> catalogued = new ArrayList<>(bundle.companies());
        catalogued.addAll(bundle.pathCompanies());
        Set<String> companyIds = new LinkedHashSet<>();
        for (Company company : catalogued) {
            companyIds.add(company.id());
        }
        Map<String, CompanyRow> catalog = graph.companies(companyIds);
        for (Company company : catalogued) {
            CompanyRow row = catalog.get(company.id());
            if (row == null || !row.name().equals(company.label())) {
                throw new GraphHandoffException(GraphHandoffFailure.COMPANY_MISMATCH);
            }
        }
        // Issues and companies share one node id space in the public graph: an issue id may not be a catalog company id.
        Set<String> issueIds = new LinkedHashSet<>();
        bundle.issues().forEach(issue -> issueIds.add(issue.id()));
        if (!graph.companies(issueIds).isEmpty()) {
            throw new GraphHandoffException(GraphHandoffFailure.COMPANY_MISMATCH);
        }

        Map<String, String> texts = new HashMap<>();
        for (Article article : bundle.articles()) {
            String key = article.articleId() + "\n" + article.articleVersion();
            ObservationFacts facts = checked.byArticle().get(key);
            // FOR UPDATE: the row stays locked until this transaction ends, so the status checked here is the status committed with.
            ArticleRow row = registry.lockArticle(article.articleId()).orElseThrow(
                    () -> new GraphHandoffException(GraphHandoffFailure.ARTICLE_UNREGISTERED));
            VersionRow version = registry.findVersion(article.articleId(), article.articleVersion()).orElseThrow(
                    () -> new GraphHandoffException(GraphHandoffFailure.ARTICLE_UNREGISTERED));
            if (!AVAILABLE.equals(row.accessStatus())
                    || !article.observations().stream().allMatch(pin -> pin.sourceId().equals(row.provider()))
                    || !sameVersion(article, version) || !facts.textArtifactId().equals(version.textArtifactId())) {
                throw new GraphHandoffException(GraphHandoffFailure.ARTICLE_MISMATCH);
            }
            ArtifactRow text = registry.findArtifact(version.textArtifactId()).orElseThrow(
                    () -> new GraphHandoffException(GraphHandoffFailure.ARTICLE_MISMATCH));
            // The app's own stored text must be byte-for-byte the text the current export proved (hash and size equal, and the
            // file itself is read back and verified against the registry), and its hash is the textSha256 the bundle's exact-text
            // sourceSupport was computed from: a bundle whose lineage rests on another text is refused.
            if (!"extracted_text".equals(text.kind()) || !text.sha256().equals(facts.textSha256())
                    || !text.sha256().equals(article.textSha256()) || text.bytes() != facts.textBytes()) {
                throw new GraphHandoffException(GraphHandoffFailure.TEXT_MISMATCH);
            }
            texts.put(key, decode(readRegistered(session, text)));
        }

        List<EvidenceRow> rows = new ArrayList<>();
        for (Evidence evidence : bundle.evidence()) {
            String text = texts.get(evidence.articleId() + "\n" + evidence.articleVersion());
            ObservationFacts facts = checked.byArticle().get(evidence.articleId() + "\n" + evidence.articleVersion());
            // Offsets are Unicode code points of the app's own text; the quote is that exact span, and its UTF-8 hash is the one
            // the bundle states. This proves the quote is where the producer says it is, not that it supports any claim.
            String quote = Text.codePointSlice(text, evidence.start(), evidence.end());
            if (quote == null || !Text.storable(quote) || !Canonical.sha256(quote).equals(evidence.quoteSha256())
                    || evidence.rawLocatorIds().isEmpty()) {
                throw new GraphHandoffException(GraphHandoffFailure.EVIDENCE_INVALID);
            }
            rows.add(new EvidenceRow(evidence.id(), evidence.articleId(), evidence.articleVersion(), facts.textArtifactId(),
                    quote, evidence.start(), evidence.end(), evidence.rawLocatorIds(), receiptArtifactId, now, now));
        }
        return new AppFacts(rows);
    }

    /**
     * Reads every article row again, still under the row lock {@link #verifyApp} took: the article must still be available and
     * still belong to the source the bundle names. Withdrawing an article (private, deleted) needs that same row, so it either
     * happened before the lock (and verifyApp refused) or it waits for this transaction's commit.
     */
    private void revalidateArticles(HandoffBundle bundle) {
        for (Article article : bundle.articles()) {
            ArticleRow row = registry.lockArticle(article.articleId()).orElseThrow(
                    () -> new GraphHandoffException(GraphHandoffFailure.ARTICLE_UNREGISTERED));
            if (!AVAILABLE.equals(row.accessStatus())
                    || !article.observations().stream().allMatch(pin -> pin.sourceId().equals(row.provider()))) {
                throw new GraphHandoffException(GraphHandoffFailure.ARTICLE_MISMATCH);
            }
        }
    }

    private static boolean sameVersion(Article article, VersionRow version) {
        boolean sameTime = switch (article.precision()) {
            case "datetime" -> version.publishedAt() != null && version.publishedDate() == null
                    && version.publishedAt().equals(HandoffTime.instant(article.publishedAt()));
            case "day" -> version.publishedAt() == null && version.publishedDate() != null
                    && version.publishedDate().toString().equals(article.publishedAt());
            default -> version.publishedAt() == null && version.publishedDate() == null;
        };
        return sameTime && article.precision().equals(version.publicationPrecision())
                && article.title().equals(version.title()) && article.url().equals(version.url());
    }

    // ---------------------------------------------------------------------------------------------- writes ---------------

    /**
     * Registers every evidence row, or, when {@code insert} is false, only proves that each one already exists. An existing row
     * is reused only when it is, column for column, the row this handoff would register ({@link #sameEvidence}); anything else
     * with the same id (another quote, text or locator list, another kind, an unverified or differently verified row) is a
     * collision and the whole import is refused. No stored row is ever updated or repaired.
     *
     * @return {registered, existing}
     */
    private int[] registerEvidence(List<EvidenceRow> rows, boolean insert) {
        int registered = 0;
        int existing = 0;
        for (EvidenceRow row : rows) {
            Optional<StoredEvidence> found = graph.findEvidence(row.id());
            if (found.isPresent()) {
                if (!sameEvidence(found.get(), row)) {
                    throw new GraphHandoffException(GraphHandoffFailure.EVIDENCE_COLLISION);
                }
                existing++;
            } else if (insert) {
                graph.insertEvidence(row);
                registered++;
            } else {
                throw new GraphHandoffException(GraphHandoffFailure.VERSION_CONFLICT);
            }
        }
        return new int[] {registered, existing};
    }

    /**
     * Whether a stored evidence row may stand for {@code wanted}: the same content (article, version, text artifact, quote,
     * offsets, locators) AND the same meaning: a body citation in code points that no summary owns, whose quote was verified
     * against a graph {@code verification_receipt} (of this or an earlier handoff, which is why the receipt id is NOT compared).
     * A row without that provenance would make the staged evidence look verified when nothing verified it.
     */
    private static boolean sameEvidence(StoredEvidence stored, EvidenceRow wanted) {
        EvidenceRow row = stored.row();
        return row.articleId().equals(wanted.articleId()) && row.articleVersion().equals(wanted.articleVersion())
                && row.textArtifactId().equals(wanted.textArtifactId()) && row.quote().equals(wanted.quote())
                && row.startOffset() == wanted.startOffset() && row.endOffset() == wanted.endOffset()
                && row.rawLocatorIds().equals(wanted.rawLocatorIds())
                && "unicode_code_point".equals(stored.offsetUnit()) && "body".equals(stored.inputKind())
                && stored.summaryAnalysisId() == null && Boolean.TRUE.equals(stored.quoteVerified())
                && row.verificationArtifactId() != null && row.verifiedAt() != null
                && RECEIPT_KIND.equals(stored.verificationKind());
    }

    /** Inserts the artifact row unless the id exists; an existing row must be identical (creation time aside). */
    private void registerArtifact(ArtifactRow wanted) {
        try {
            registry.insertArtifactIfAbsent(wanted);
        } catch (DuplicateKeyException storageUriTaken) {
            // The id is new but another artifact already owns this URI: URIs are never shared or overwritten.
            throw new GraphHandoffException(GraphHandoffFailure.ARTIFACT_CONFLICT);
        }
        ArtifactRow stored = registry.findArtifact(wanted.id()).orElseThrow(
                () -> new GraphHandoffException(GraphHandoffFailure.INTERNAL_ERROR));
        if (!stored.kind().equals(wanted.kind()) || !stored.storageUri().equals(wanted.storageUri())
                || !stored.sha256().equals(wanted.sha256()) || stored.bytes() != wanted.bytes()
                || !stored.mediaType().equals(wanted.mediaType())) {
            throw new GraphHandoffException(GraphHandoffFailure.ARTIFACT_CONFLICT);
        }
    }

    private static ArtifactFileStore.StoredFile put(ArtifactFileStore.Session session,
            List<ArtifactFileStore.StoredFile> created, String directory, String fileName, byte[] content) {
        try {
            ArtifactFileStore.StoredFile file = session.put(directory, fileName, content);
            created.add(file);
            return file;
        } catch (ArtifactStoreException error) {
            log.warn("graph handoff import file failed: {} ({})", error.reason(), error.detail());
            throw new GraphHandoffException(error.reason() == ArtifactStoreException.Reason.CONFLICT
                    ? GraphHandoffFailure.ARTIFACT_FILE_CONFLICT : GraphHandoffFailure.ARTIFACT_STORE_UNAVAILABLE);
        }
    }

    /** A registered file read back and verified against its registry hash and size. */
    private static byte[] readRegistered(ArtifactFileStore.Session session, ArtifactRow artifact) {
        try {
            return session.read(artifact.storageUri(), artifact.sha256(), artifact.bytes());
        } catch (ArtifactStoreException error) {
            log.warn("graph handoff import file read failed: {} ({})", error.reason(), error.detail());
            throw new GraphHandoffException(error.reason() == ArtifactStoreException.Reason.CONFLICT
                    ? GraphHandoffFailure.TEXT_MISMATCH : GraphHandoffFailure.ARTIFACT_STORE_UNAVAILABLE);
        }
    }

    private static String decode(byte[] utf8) {
        try {
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(utf8)).toString();
        } catch (CharacterCodingException error) {
            throw new GraphHandoffException(GraphHandoffFailure.TEXT_MISMATCH);
        }
    }

    private static byte[] snapshotBytes(String versionId, VerifiedHandoff handoff) {
        try {
            byte[] bytes = HandoffSnapshotWriter.snapshot(versionId, handoff);
            // The reader of the public API must be able to read exactly this file; anything it would refuse is refused here.
            GraphSnapshotCodec.read(bytes, versionId);
            return bytes;
        } catch (StrictJson.Malformed | GraphSnapshotUnavailableException invalid) {
            throw new GraphHandoffException(GraphHandoffFailure.SNAPSHOT_INVALID);
        }
    }

    private static StoredFileFact fact(String artifactId, ArtifactFileStore.StoredFile file) {
        return new StoredFileFact(artifactId, file.sha256(), file.bytes(), file.created() ? "created" : "existing");
    }

    private static Staged result(Outcome outcome, Checked checked, HandoffBundle bundle, int[] evidenceCounts,
            StoredFileFact snapshot, StoredFileFact receipt) {
        Map<String, Integer> origins = new TreeMap<>();
        for (Relation relation : bundle.relations()) {
            origins.merge(relation.origin(), 1, Integer::sum);
        }
        Map<String, Integer> approvalBases = new TreeMap<>();
        for (HandoffBundle.Approval approval : bundle.approvals()) {
            approvalBases.merge(approval.kind(), 1, Integer::sum);
        }
        VerifiedHandoff handoff = checked.handoff();
        return new Staged(bundle.handoffId(), HandoffSnapshotWriter.versionId(bundle.handoffId()), outcome,
                handoff.manifestDigest(), handoff.bundleDigest(), handoff.contentDigest(), bundle.sourceKind(),
                bundle.executionMode(), bundle.recordingKind(), origins, approvalBases, bundle.companies().size(),
                bundle.issues().size(), bundle.relations().size(), bundle.articles().size(), bundle.evidence().size(),
                evidenceCounts[0], evidenceCounts[1], Objects.requireNonNull(snapshot), Objects.requireNonNull(receipt));
    }
}
