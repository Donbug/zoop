package com.zoop.document.analysis;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Supplier;

import com.zoop.ai.AiAnalysisClient;
import com.zoop.ai.AiClientException;
import com.zoop.ai.AiServiceErrorException;
import com.zoop.ai.AnalysisAcknowledgement;
import com.zoop.ai.AnalysisJobStatus;
import com.zoop.ai.AnalysisResult;
import com.zoop.ai.ExecutionMode;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.DocumentImportException;
import com.zoop.document.analysis.repository.AnalysisRow;
import com.zoop.document.analysis.repository.DocumentAnalysisRepository;
import com.zoop.document.analysis.repository.ExecutionRow;
import com.zoop.document.analysis.service.ArtifactFile;
import com.zoop.document.analysis.service.AvailableFields;
import com.zoop.document.analysis.service.DocumentAnalysisService;
import com.zoop.document.analysis.service.EvidenceDraft;
import com.zoop.document.analysis.service.Reservation;
import com.zoop.document.analysis.service.ReserveCommand;
import com.zoop.document.analysis.service.SettleCommand;
import com.zoop.document.analysis.service.Settlement;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.IngestionExporter;
import com.zoop.document.importer.VerifiedDocument;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;

/**
 * Runs an operator batch of one command against one AI service, one item at a time, stopping at the first failing item.
 * It holds the operator lock of the artifact store for the whole run, so a document import and an analysis (or two analyses)
 * never run at the same time.
 *
 * <p><b>prepare</b> reserves an analysis and never calls the AI service: a fresh S2-1 export of the document (the importer's
 * own {@code --require-store} export and checks), the operator's flat grant registry, the registered article and the company
 * catalog are consulted, the immutable {@code ai_submit} file is stored, and one short transaction commits the pending
 * {@code document_analyses} row with its newly issued AI job id and the submit's artifact row.
 *
 * <p><b>advance</b> reads the AI job's status first. A job the service does not know yet is submitted from the stored bytes
 * under the same job id (never a new one, never a second submit once the service answers a status); otherwise the service's own
 * {@code next} decides. A finished job's result is verified (see {@link ResultAssessor}) and settled in one short transaction
 * together with its receipts, counted AI executions and evidence. Pending is a success; a result that cannot be attributed
 * writes nothing and leaves the analysis pending.
 *
 * <p>A file this item created is removed again when a defined failure rolls the transaction back, or when a fresh authority
 * check under the settlement locks downgrades available content to withheld. After a database or commit failure the outcome is
 * unknown and the file stays, because the row may have committed and the next run adopts it after a byte comparison.
 */
public final class DocumentAnalyzer {
    static final String SUBMIT_DIRECTORY = "ai_submit";
    static final String RECEIPT_DIRECTORY = "ai_call_receipt";
    static final String RESULT_DIRECTORY = "analysis_result";
    static final String VERIFIER_DIRECTORY = "semantic_receipt";
    static final String EXACT_DIRECTORY = "exact_receipt";
    private static final String AVAILABLE = "available";
    private static final Logger log = LoggerFactory.getLogger(DocumentAnalyzer.class);

    private final Path grants;
    private final IngestionExporter exporter;
    private final IngestionExportParser exportParser;
    private final ArtifactFileStore store;
    private final DocumentRegistryRepository registry;
    private final DocumentAnalysisRepository analyses;
    private final DocumentAnalysisService service;
    private final AiAnalysisClient client;
    private final Clock clock;
    private final ResultAssessor assessor = new ResultAssessor();
    private final Supplier<String> hexSource;

    public DocumentAnalyzer(Path grants, IngestionExporter exporter, IngestionExportParser exportParser, ArtifactFileStore store,
            DocumentRegistryRepository registry, DocumentAnalysisRepository analyses, DocumentAnalysisService service,
            AiAnalysisClient client, Clock clock) {
        this(grants, exporter, exportParser, store, registry, analyses, service, client, clock, new RandomHex());
    }

    /** The ids of new analyses come from {@code hexSource}: 32 lowercase hex characters, random in production. */
    DocumentAnalyzer(Path grants, IngestionExporter exporter, IngestionExportParser exportParser, ArtifactFileStore store,
            DocumentRegistryRepository registry, DocumentAnalysisRepository analyses, DocumentAnalysisService service,
            AiAnalysisClient client, Clock clock, Supplier<String> hexSource) {
        this.hexSource = hexSource;
        this.grants = grants;
        this.exporter = exporter;
        this.exportParser = exportParser;
        this.store = store;
        this.registry = registry;
        this.analyses = analyses;
        this.service = service;
        this.client = client;
        this.clock = clock;
    }

    public AnalysisRunResult run(AnalysisRequest request) {
        ArtifactFileStore.Session session;
        try {
            session = store.open();
        } catch (ArtifactStoreException error) {
            log.warn("document analysis did not start: {} ({})", error.reason(), error.detail());
            AnalysisFailure failure = error.reason() == ArtifactStoreException.Reason.BUSY
                    ? AnalysisFailure.ANALYSIS_BUSY : AnalysisFailure.ARTIFACT_STORE_UNAVAILABLE;
            List<AnalysisItemResult> notAttempted = new ArrayList<>();
            for (int index = 0; index < request.size(); index++) {
                notAttempted.add(new AnalysisItemResult.NotAttempted(index));
            }
            return AnalysisRunResult.requestFailed(request.command(), failure, Map.of(), notAttempted);
        }
        try (session) {
            List<AnalysisItemResult> results = new ArrayList<>(request.size());
            boolean stopped = false;
            for (int index = 0; index < request.size(); index++) {
                if (stopped) {
                    results.add(new AnalysisItemResult.NotAttempted(index));
                    continue;
                }
                AnalysisItemResult result = runItem(session, index, request);
                stopped = result instanceof AnalysisItemResult.Failed;
                results.add(result);
            }
            return new AnalysisRunResult(request.command(), null, Map.of(), results);
        }
    }

    private AnalysisItemResult runItem(ArtifactFileStore.Session session, int index, AnalysisRequest request) {
        try {
            if (request instanceof AnalysisRequest.Prepare prepare) {
                return prepare(session, index, prepare.items().get(index));
            }
            return advance(session, index, ((AnalysisRequest.Advance) request).items().get(index));
        } catch (AnalysisException failure) {
            log.warn("document analysis {} item {} failed: {}", request.command(), index, failure.failure().code());
            return new AnalysisItemResult.Failed(index, failure.failure(), failure.details());
        } catch (DataAccessException | TransactionException unknownOutcome) {
            // A connection or commit failure: the row may or may not exist. Files are kept and the next run adopts them.
            log.error("document analysis {} item {} database failure: {}", request.command(), index,
                    unknownOutcome.getClass().getSimpleName());
            return new AnalysisItemResult.Failed(index, AnalysisFailure.DATABASE_UNAVAILABLE, Map.of());
        } catch (RuntimeException unexpected) {
            // State is unknown: keep any file (recoverable) and report without the exception's text.
            log.error("document analysis {} item {} failed unexpectedly: {}", request.command(), index,
                    unexpected.getClass().getName());
            return new AnalysisItemResult.Failed(index, AnalysisFailure.INTERNAL_ERROR, Map.of());
        }
    }

    // ---- prepare ---------------------------------------------------------------------------------------------------------

    private AnalysisItemResult prepare(ArtifactFileStore.Session session, int index, AnalysisRequest.PrepareItem item) {
        // P1: a fresh export (the importer's own rights and store checks) validated against exactly what was asked for.
        VerifiedDocument document;
        try {
            document = exportParser.parse(exporter.export(item.observation()), item.observation());
        } catch (DocumentImportException refused) {
            throw translate(refused);
        }

        // P2: the registered document, the company, and the operator's current grant, without locks.
        String articleId = item.observation().documentId();
        String articleVersion = item.observation().documentVersion();
        ArticleRow article = registry.findArticle(articleId)
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
        if (!article.provider().equals(item.observation().sourceId())) {
            throw new AnalysisException(AnalysisFailure.ARTICLE_PROVIDER_CONFLICT);
        }
        if (!AVAILABLE.equals(article.accessStatus())) {
            throw new AnalysisException(AnalysisFailure.ARTICLE_ACCESS_UNAVAILABLE);
        }
        registry.findVersion(articleId, articleVersion)
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
        String companyName = analyses.findCompanyName(item.companyId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.COMPANY_UNKNOWN));
        AnalysisStage stage = AnalysisStage.ofKind(item.kind()).orElseThrow(() -> new AnalysisException(AnalysisFailure.REQUEST_INVALID));
        Instant checkedAt = clock.instant();
        GrantRegistry registryFile = GrantRegistry.read(grants);
        boolean replay = item.mode() == ExecutionMode.REPLAY;
        String denial = GrantRegistry.evaluate(registryFile.current(item.grant().grantId()).orElse(null), article.provider(),
                item.grant().revision(), GrantRegistry.purposesOf(item.kind().wire()),
                replay ? List.of(GrantRegistry.REPLAY_RECIPIENT) : List.of(), replay, checkedAt);
        if (denial != null) {
            throw AnalysisException.of(AnalysisFailure.GRANT_DENIED, "grantCode", denial);
        }

        // P3: the immutable request. The job id is issued now and never changes.
        String aiJobId = "s1-" + randomHex();
        String analysisId = "da-" + randomHex();
        AnalysisSubmit submit;
        try {
            submit = AnalysisSubmit.build(aiJobId, item.kind(), item.mode(), item.sourceKind(), document.document(),
                    item.companyId(), companyName, item.grant().grantId(), item.grant().revision());
        } catch (StrictJson.Malformed malformed) {
            throw new AnalysisException(AnalysisFailure.EXPORT_INVALID);
        }
        if (!submit.withinRequestLimit()) {
            throw new AnalysisException(AnalysisFailure.REQUEST_TOO_LARGE);
        }
        String scopeCompany = stage.companyScoped() ? item.companyId() : null;
        for (AnalysisRow earlier : analyses.availableInScope(articleId, articleVersion, stage.wire(), scopeCompany)) {
            // The worker's cache would return the very same result version, which the ERD allows only once.
            if (loadSubmit(session, earlier).identity().equals(submit.identity())) {
                throw AnalysisException.of(AnalysisFailure.ANALYSIS_UNCHANGED, "analysisId", earlier.id());
            }
        }

        // P4: the file, then P5: one transaction. Nothing external is called until both are durable.
        byte[] bytes = submit.bytes();
        ArtifactFileStore.StoredFile file = put(session, SUBMIT_DIRECTORY, "submit-" + aiJobId + ".json", bytes);
        try {
            Reservation reservation = service.reserve(new ReserveCommand(analysisId, aiJobId, articleId, articleVersion, stage,
                    item.companyId(), companyName, item.expectedLatest(), item.grant().grantId(), item.grant().revision(),
                    checkedAt, document.textArtifactId(), Canonical.sha256(document.textUtf8()), document.textUtf8().length,
                    new ArtifactFile("submit-" + aiJobId, "ai_submit", file.uri(), file.sha256(), file.bytes())));
            return new AnalysisItemResult.Prepared(index, reservation.analysisId(), reservation.aiJobId(),
                    reservation.requestNo(), reservation.stage());
        } catch (AnalysisException rolledBack) {
            if (session.discard(file)) {
                log.info("document analysis item {} removed the submit file it had created", index);
            }
            throw rolledBack;
        }
    }

    // ---- advance ---------------------------------------------------------------------------------------------------------

    private AnalysisItemResult advance(ArtifactFileStore.Session session, int index, AnalysisRequest.AdvanceItem item) {
        AnalysisRow row = analyses.find(item.analysisId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.ANALYSIS_UNKNOWN));
        if (!"pending".equals(row.status())) {
            return new AnalysisItemResult.AlreadySettled(index, row.id(), row.status(), row.reason());
        }
        AnalysisSubmit submit = loadSubmit(session, row);

        AnalysisJobStatus status;
        try {
            status = client.status(row.aiJobId());
        } catch (AiServiceErrorException error) {
            if (error.httpStatus() != 404 || !"job_not_found".equals(error.code())) {
                throw AnalysisException.of(AnalysisFailure.STATUS_UNAVAILABLE, "aiCode", error.code());
            }
            // The service has not registered this job id: send the stored bytes, under the same id, once.
            requireCurrentSendAuthority(row, submit);
            AnalysisAcknowledgement acknowledgement;
            try {
                acknowledgement = client.submit(submit.toSubmission());
            } catch (AiClientException refused) {
                return refusedSubmit(session, index, row, submit, refused);
            } catch (IllegalArgumentException invalid) {
                throw AnalysisException.of(AnalysisFailure.SUBMIT_REFUSED, "aiCode", "client_rejected");
            }
            status = acknowledgement.status();
        } catch (AiClientException error) {
            throw new AnalysisException(AnalysisFailure.STATUS_UNAVAILABLE);
        }
        if (!status.jobId().equals(row.aiJobId()) || status.kind() != submit.kind() || status.mode() != submit.mode()) {
            throw new AnalysisException(AnalysisFailure.STATUS_BINDING_INVALID);
        }
        switch (status.next()) {
            case WAIT:
                return new AnalysisItemResult.Pending(index, row.id(), row.aiJobId(), "wait");
            case RECOVER:
                return recover(index, row, submit, item);
            case OPERATOR_RECONCILE:
                throw new AnalysisException(AnalysisFailure.OPERATOR_RECONCILE_REQUIRED);
            case NONE:
                if (status.state() != AnalysisJobStatus.State.FAILED && status.state() != AnalysisJobStatus.State.CANCELLED) {
                    throw AnalysisException.of(AnalysisFailure.STATUS_BINDING_INVALID, "detail", "next_none");
                }
                return settleFinished(session, index, row, submit, status, false);
            case FETCH_RESULT:
                if (status.state() != AnalysisJobStatus.State.READY) {
                    throw AnalysisException.of(AnalysisFailure.STATUS_BINDING_INVALID, "detail", "next_fetch");
                }
                return settleFinished(session, index, row, submit, status, true);
            default:
                throw new AnalysisException(AnalysisFailure.STATUS_BINDING_INVALID);
        }
    }

    /** A submit the service refused. Only a 4xx answer proves nothing was registered; everything else is unknown or retryable. */
    private AnalysisItemResult refusedSubmit(ArtifactFileStore.Session session, int index, AnalysisRow row, AnalysisSubmit submit,
            AiClientException refused) {
        if (refused.requestMaybeProcessed()) {
            throw new AnalysisException(AnalysisFailure.SUBMIT_OUTCOME_UNKNOWN);
        }
        if (refused instanceof AiServiceErrorException rejection) {
            if (rejection.httpStatus() == 422 || rejection.httpStatus() == 413) {
                // The service decided the request itself is invalid and registered nothing: a terminal failure.
                return settleTerminal(session, index, row, submit, "failed", rejection.code(), null, List.of(), null);
            }
            if ("idempotency_conflict".equals(rejection.code())) {
                throw new AnalysisException(AnalysisFailure.SUBMIT_CONFLICT);
            }
            throw AnalysisException.of(AnalysisFailure.SUBMIT_REFUSED, "aiCode", rejection.code());
        }
        throw AnalysisException.of(AnalysisFailure.SUBMIT_REFUSED, "aiCode", "transport");
    }

    private AnalysisItemResult recover(int index, AnalysisRow row, AnalysisSubmit submit, AnalysisRequest.AdvanceItem item) {
        if (!item.recover()) {
            throw new AnalysisException(AnalysisFailure.RECOVER_REQUIRED);
        }
        requireCurrentSendAuthority(row, submit);
        try {
            client.recover(row.aiJobId());
        } catch (AiServiceErrorException error) {
            throw AnalysisException.of(AnalysisFailure.RECOVER_REFUSED, "aiCode", error.code());
        } catch (AiClientException error) {
            throw new AnalysisException(AnalysisFailure.RECOVER_REFUSED);
        }
        return new AnalysisItemResult.Pending(index, row.id(), row.aiJobId(), "recovering");
    }

    /** A status read is always allowed; this fresh app-side decision is required only immediately before a send or recovery. */
    private void requireCurrentSendAuthority(AnalysisRow row, AnalysisSubmit submit) {
        ArticleRow article = registry.findArticle(row.articleId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
        if (!AVAILABLE.equals(article.accessStatus())) {
            throw new AnalysisException(AnalysisFailure.ARTICLE_ACCESS_UNAVAILABLE);
        }
        boolean replay = submit.mode() == ExecutionMode.REPLAY;
        String denial = currentGrantDenial(submit, article.provider(),
                replay ? List.of(GrantRegistry.REPLAY_RECIPIENT) : List.of(), replay, clock.instant());
        if (denial != null) {
            throw AnalysisException.of(AnalysisFailure.GRANT_DENIED, "grantCode", denial);
        }
    }

    /** Reads the flat registry now; a read/parse failure propagates as unavailable rather than becoming a denial settlement. */
    private String currentGrantDenial(AnalysisSubmit submit, String sourceId, List<String> recipients,
            boolean requireRecipients, Instant now) {
        if (!submit.sourceId().equals(sourceId)) {
            return "grant_revision_or_source_changed";
        }
        GrantRegistry current = GrantRegistry.read(grants);
        return GrantRegistry.evaluate(current.current(submit.grantId()).orElse(null), sourceId, submit.grantRevision(),
                GrantRegistry.purposesOf(submit.kind().wire()), recipients, requireRecipients, now);
    }

    /** A terminal or ready job: read its result and settle it (or report that its receipts are not complete yet). */
    private AnalysisItemResult settleFinished(ArtifactFileStore.Session session, int index, AnalysisRow row, AnalysisSubmit submit,
            AnalysisJobStatus seen, boolean ready) {
        if (seen.unreceiptedAttempts() > 0) {
            return new AnalysisItemResult.Pending(index, row.id(), row.aiJobId(), "receipts_incomplete");
        }
        AnalysisResult result;
        try {
            result = client.result(row.aiJobId());
        } catch (AiServiceErrorException error) {
            throw AnalysisException.of(AnalysisFailure.AI_RESULT_UNAVAILABLE, "aiCode", error.code());
        } catch (AiClientException error) {
            throw new AnalysisException(AnalysisFailure.AI_RESULT_UNAVAILABLE);
        }
        AnalysisJobStatus now = result.status();
        boolean stable = ready ? now.state() == AnalysisJobStatus.State.READY
                : now.state() == AnalysisJobStatus.State.FAILED || now.state() == AnalysisJobStatus.State.CANCELLED;
        if (!now.jobId().equals(row.aiJobId()) || now.kind() != submit.kind() || now.mode() != submit.mode()
                || !now.inputDigest().equals(seen.inputDigest()) || !stable) {
            throw AnalysisException.of(AnalysisFailure.RESULT_BINDING_INVALID, "detail", "status");
        }
        if (now.unreceiptedAttempts() > 0) {
            return new AnalysisItemResult.Pending(index, row.id(), row.aiJobId(), "receipts_incomplete");
        }
        if (!ready) {
            ResultAssessor.requireReceipts(submit, result.receipts());
            String reason = now.failure() != null ? now.failure().code()
                    : now.state() == AnalysisJobStatus.State.CANCELLED ? "cancelled" : "ai_job_failed";
            return settleTerminal(session, index, row, submit, "failed", reason,
                    new ResultAssessor.ReceiptScope(row.aiJobId(), row.id()), result.receipts(), null);
        }

        boolean delivered = result.delivery().state() == AnalysisResult.Delivery.State.AVAILABLE;
        StoredText text = delivered ? storedText(session, row, submit) : null;
        ArticleRow article = registry.findArticle(row.articleId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
        // The operator's registry and the article are read now, not when the analysis was prepared.
        GrantRegistry current = GrantRegistry.read(grants);
        ResultAssessor.Assessment assessment = assessor.assess(new ResultAssessor.Input(row.id(), row.aiJobId(), submit, result,
                text == null ? null : text.sha256(), aiJobId -> creator(session, aiJobId), current, clock.instant(),
                AVAILABLE.equals(article.accessStatus())));
        if (assessment instanceof ResultAssessor.Available available) {
            return settleTerminal(session, index, row, submit, AVAILABLE, null, available.scope(), result.receipts(),
                    available.content());
        }
        ResultAssessor.Withheld withheld = (ResultAssessor.Withheld) assessment;
        return settleTerminal(session, index, row, submit, "withheld", withheld.reason(), withheld.scope(), result.receipts(), null);
    }

    private Optional<ResultAssessor.Creator> creator(ArtifactFileStore.Session session, String aiJobId) {
        return analyses.findByAiJobId(aiJobId)
                .map(found -> new ResultAssessor.Creator(found.id(), loadSubmit(session, found).identity()));
    }

    // ---- settlement -------------------------------------------------------------------------------------------------------

    /** One planned file: stored first, registered by the settlement transaction. */
    private record Planned(String directory, String id, String kind, byte[] bytes) {
    }

    private AnalysisItemResult settleTerminal(ArtifactFileStore.Session session, int index, AnalysisRow row, AnalysisSubmit submit,
            String outcome, String reason, ResultAssessor.ReceiptScope scope, List<AnalysisResult.Receipt> receipts,
            ResultAssessor.Content content) {
        List<Planned> planned = new ArrayList<>();
        List<ExecutionRow> executions = new ArrayList<>();
        if (scope != null) {
            for (AnalysisResult.Receipt receipt : receipts) {
                String id = ReceiptRecords.artifactId(scope.creatorJobId(), receipt.attemptId());
                planned.add(new Planned(RECEIPT_DIRECTORY, id, "ai_call_receipt",
                        ReceiptRecords.artifactBytes(scope.creatorJobId(), receipt)));
                executions.add(ReceiptRecords.execution(scope.ownerAnalysisId(), scope.creatorJobId(), submit, receipt));
            }
        }
        List<EvidenceDraft> evidence = new ArrayList<>();
        AvailableFields available = null;
        if (content != null) {
            planned.add(new Planned(RESULT_DIRECTORY, content.main().artifactId(), "analysis_result",
                    Canonical.bytes(content.main().node())));
            planned.add(new Planned(VERIFIER_DIRECTORY, content.verifier().artifactId(), "semantic_receipt",
                    Canonical.bytes(content.verifier().node())));
            planned.add(new Planned(EXACT_DIRECTORY, content.exactReceiptId(), "exact_receipt", content.exactReceipt()));
            for (ResultAssessor.EvidenceSeed seed : content.evidence()) {
                AiPayload.Citation citation = seed.citation();
                evidence.add(new EvidenceDraft(seed.id(), row.articleId(), row.articleVersion(), submit.textArtifactId(),
                        citation.quote(), citation.start(), citation.end(), citation.rawLocatorIds()));
            }
            available = new AvailableFields(content.resultJson(), content.resultVersion(), content.main().artifactId(),
                    content.exactReceiptId(), content.verifier().artifactId(), content.producedAt());
        }
        AnalysisResult.Receipt generation = content != null ? content.generation()
                : receipts.stream().filter(r -> r.stage() == submit.kind()).findFirst().orElse(null);

        List<ArtifactFileStore.StoredFile> created = new ArrayList<>();
        List<ArtifactFileStore.StoredFile> createdContent = new ArrayList<>();
        List<ArtifactFile> files = new ArrayList<>();
        try {
            for (Planned file : planned) {
                ArtifactFileStore.StoredFile stored = put(session, file.directory(), file.id() + ".json", file.bytes());
                if (stored.created()) {
                    created.add(stored);
                    if (!"ai_call_receipt".equals(file.kind())) {
                        createdContent.add(stored);
                    }
                }
                files.add(new ArtifactFile(file.id(), file.kind(), stored.uri(), stored.sha256(), stored.bytes()));
            }
            SettleCommand.CurrentAuthority currentAuthority = content == null ? null
                    : (sourceId, now) -> currentGrantDenial(submit, sourceId, content.recipients(), true, now);
            Settlement settlement = service.settle(new SettleCommand(row.id(), row.aiJobId(), outcome, reason,
                    generation == null ? null : generation.model(), generation == null ? null : generation.promptVersion(),
                    generation == null ? null : generation.reasoningEffort().orElse(null), files, executions, evidence,
                    available, currentAuthority));
            if (content != null && !AVAILABLE.equals(settlement.status())) {
                for (int position = createdContent.size() - 1; position >= 0; position--) {
                    session.discard(createdContent.get(position));
                }
            }
            return new AnalysisItemResult.Settled(index, row.id(), settlement.status(), settlement.reason(),
                    settlement.executionsCreated(), settlement.executionsExisting(), settlement.evidence());
        } catch (AnalysisException rolledBack) {
            for (int position = created.size() - 1; position >= 0; position--) {
                session.discard(created.get(position));
            }
            throw rolledBack;
        }
    }

    // ---- reading stored artifacts --------------------------------------------------------------------------------------

    private record StoredText(String text, String sha256) {
    }

    /** The registered submit of an analysis, read back through the verified read and bound to its row. */
    private AnalysisSubmit loadSubmit(ArtifactFileStore.Session session, AnalysisRow row) {
        ArtifactRow artifact = registry.findArtifact("submit-" + row.aiJobId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.SUBMIT_ARTIFACT_INVALID));
        if (!"ai_submit".equals(artifact.kind()) || !"application/json".equals(artifact.mediaType())) {
            throw new AnalysisException(AnalysisFailure.SUBMIT_ARTIFACT_INVALID);
        }
        AnalysisSubmit submit;
        try {
            submit = AnalysisSubmit.parse(read(session, artifact));
        } catch (StrictJson.Malformed malformed) {
            throw new AnalysisException(AnalysisFailure.SUBMIT_ARTIFACT_INVALID);
        }
        AnalysisStage stage = AnalysisStage.fromWire(row.stage())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.SUBMIT_ARTIFACT_INVALID));
        boolean bound = submit.jobId().equals(row.aiJobId()) && submit.kind() == stage.kind()
                && submit.documentId().equals(row.articleId()) && submit.documentVersion().equals(row.articleVersion())
                && (!stage.companyScoped() || submit.companyId().equals(row.companyId()))
                && submit.grantId().equals(row.grantReference()) && submit.grantRevision().equals(row.grantRevision());
        if (!bound) {
            throw new AnalysisException(AnalysisFailure.SUBMIT_ARTIFACT_INVALID);
        }
        return submit;
    }

    /** The registered text of the analysed version, which must be exactly the text the submit carries. */
    private StoredText storedText(ArtifactFileStore.Session session, AnalysisRow row, AnalysisSubmit submit) {
        VersionRow version = registry.findVersion(row.articleId(), row.articleVersion())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
        ArtifactRow artifact = registry.findArtifact(version.textArtifactId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.TEXT_ARTIFACT_MISMATCH));
        if (!version.textArtifactId().equals(submit.textArtifactId()) || !"extracted_text".equals(artifact.kind())) {
            throw new AnalysisException(AnalysisFailure.TEXT_ARTIFACT_MISMATCH);
        }
        String text = decode(read(session, artifact));
        if (text == null || !text.equals(submit.text())) {
            throw new AnalysisException(AnalysisFailure.TEXT_ARTIFACT_MISMATCH);
        }
        return new StoredText(text, artifact.sha256());
    }

    private static String decode(byte[] bytes) {
        try {
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException error) {
            return null;
        }
    }

    private static byte[] read(ArtifactFileStore.Session session, ArtifactRow artifact) {
        try {
            return session.read(artifact.storageUri(), artifact.sha256(), artifact.bytes());
        } catch (ArtifactStoreException error) {
            log.warn("document analysis artifact read failed: {} ({})", error.reason(), error.detail());
            throw new AnalysisException(error.reason() == ArtifactStoreException.Reason.CONFLICT
                    ? AnalysisFailure.ARTIFACT_FILE_CONFLICT : AnalysisFailure.ARTIFACT_STORE_UNAVAILABLE);
        }
    }

    private static ArtifactFileStore.StoredFile put(ArtifactFileStore.Session session, String directory, String fileName,
            byte[] content) {
        try {
            return session.put(directory, fileName, content);
        } catch (ArtifactStoreException error) {
            log.warn("document analysis file failed: {} ({})", error.reason(), error.detail());
            throw new AnalysisException(error.reason() == ArtifactStoreException.Reason.CONFLICT
                    ? AnalysisFailure.ARTIFACT_FILE_CONFLICT : AnalysisFailure.ARTIFACT_STORE_UNAVAILABLE);
        }
    }

    private static AnalysisException translate(DocumentImportException refused) {
        Map<String, String> details = new LinkedHashMap<>();
        if (refused.ingestionCode() != null) {
            details.put("ingestionCode", refused.ingestionCode());
        }
        for (AnalysisFailure candidate : AnalysisFailure.values()) {
            if (candidate.code().equals(refused.failure().code())) {
                return new AnalysisException(candidate, details);
            }
        }
        return new AnalysisException(AnalysisFailure.INTERNAL_ERROR);
    }

    private String randomHex() {
        return hexSource.get();
    }

    /** 128 random bits from a {@link SecureRandom}. */
    private static final class RandomHex implements Supplier<String> {
        private final SecureRandom random = new SecureRandom();

        @Override
        public String get() {
            byte[] bytes = new byte[16];
            random.nextBytes(bytes);
            return HexFormat.of().formatHex(bytes);
        }
    }
}
