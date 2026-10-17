package com.zoop.document.importer;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import com.zoop.document.service.DocumentRegistrationService;
import com.zoop.document.service.RegistrationCommand;
import com.zoop.document.service.RegistrationOutcome;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;

/**
 * Runs a validated batch: for each item, in order, one fresh S2-1 export, strict validation, an immutable id-addressed
 * text file, and one short database transaction. The run stops at the first failing item; earlier items are committed
 * and reported as such, later ones are {@code not_attempted}.
 *
 * <p>The whole run holds the operator lock of the artifact store, so no other importer can create, adopt or delete a file
 * meanwhile. A file this item created is deleted again only when the registration is known to have rolled back (a
 * {@link DocumentImportException}); when the database outcome is unknown (connection or commit failure) the file stays,
 * because the row may have committed, and the next import of the same item adopts it after the byte comparison. A file
 * that already existed is never deleted.
 */
public final class DocumentImporter {
    static final String TEXT_DIRECTORY = "extracted_text";
    private static final Logger log = LoggerFactory.getLogger(DocumentImporter.class);

    private final IngestionExporter exporter;
    private final IngestionExportParser parser;
    private final ArtifactFileStore store;
    private final DocumentRegistrationService registration;

    public DocumentImporter(IngestionExporter exporter, IngestionExportParser parser, ArtifactFileStore store,
            DocumentRegistrationService registration) {
        this.exporter = exporter;
        this.parser = parser;
        this.store = store;
        this.registration = registration;
    }

    public DocumentImportResult run(ImportRequest request) {
        ArtifactFileStore.Session session;
        try {
            session = store.open();
        } catch (ArtifactStoreException error) {
            log.warn("document import did not start: {} ({})", error.reason(), error.detail());
            DocumentImportFailure failure = error.reason() == ArtifactStoreException.Reason.BUSY
                    ? DocumentImportFailure.IMPORT_BUSY : DocumentImportFailure.ARTIFACT_STORE_UNAVAILABLE;
            List<ItemResult> notAttempted = new ArrayList<>();
            for (int index = 0; index < request.items().size(); index++) {
                notAttempted.add(new ItemResult.NotAttempted(index));
            }
            return DocumentImportResult.requestFailed(failure, notAttempted);
        }
        try (session) {
            List<ItemResult> results = new ArrayList<>(request.items().size());
            boolean stopped = false;
            for (int index = 0; index < request.items().size(); index++) {
                if (stopped) {
                    results.add(new ItemResult.NotAttempted(index));
                    continue;
                }
                ItemResult result = runItem(session, index, request.items().get(index));
                stopped = result instanceof ItemResult.Failed;
                results.add(result);
            }
            return new DocumentImportResult(null, List.copyOf(results));
        }
    }

    private ItemResult runItem(ArtifactFileStore.Session session, int index, ImportItem item) {
        try {
            return importItem(session, index, item);
        } catch (DocumentImportException failure) {
            log.warn("document import item {} failed: {}", index, failure.failure().code());
            return new ItemResult.Failed(index, failure.failure(), failure.ingestionCode(),
                    failure.hasCurrentVersion(), failure.currentVersion());
        } catch (RuntimeException unexpected) {
            // State is unknown: keep any file (recoverable) and report without the exception's text.
            log.error("document import item {} failed unexpectedly: {}", index, unexpected.getClass().getName());
            return new ItemResult.Failed(index, DocumentImportFailure.INTERNAL_ERROR, null, false, null);
        }
    }

    private ItemResult importItem(ArtifactFileStore.Session session, int index, ImportItem item) {
        VerifiedDocument document = parser.parse(exporter.export(item.observation()), item.observation());
        CollectedProvenance collected = document.collected();
        if (collected != null && !collected.documentKind().equals(item.kind().wire())) {
            // The operator declared one kind when collecting and another when importing: refuse instead of choosing.
            throw new DocumentImportException(DocumentImportFailure.ARTICLE_KIND_CONFLICT);
        }
        ArtifactFileStore.StoredFile file = storeText(session, document);
        // A collected document's time of observation is the actual fetch time, not the later ledger receipt time.
        Instant collectedAt = collected != null ? collected.fetchedAt() : document.observedAt();
        RegistrationOutcome outcome;
        try {
            outcome = registration.register(new RegistrationCommand(
                    document.observation().documentId(), document.observation().documentVersion(),
                    document.observation().sourceId(), item.kind(), document.textArtifactId(), file.uri(), file.sha256(),
                    file.bytes(), document.title(), document.url(), document.publishedAt(), document.publishedDate(),
                    document.publicationPrecision(), collectedAt, item.pointer()));
        } catch (DocumentImportException rolledBack) {
            if (session.discard(file)) {
                log.info("document import item {} removed the text file it had created", index);
            }
            throw rolledBack;
        } catch (DataAccessException | TransactionException unknownOutcome) {
            log.error("document import item {} database failure: {}", index, unknownOutcome.getClass().getSimpleName());
            throw new DocumentImportException(DocumentImportFailure.DATABASE_UNAVAILABLE);
        }
        return new ItemResult.Imported(index, document.observation().documentId(),
                document.observation().documentVersion(), document.textArtifactId(), outcome.article(),
                outcome.artifact(), RegistrationOutcome.Presence.of(file.created()), outcome.version(), outcome.pointer(),
                outcome.currentVersion(), outcome.collectedAt(), document.grantId(), document.grantRevision(),
                document.publicationPrecision(), collected);
    }

    private static ArtifactFileStore.StoredFile storeText(ArtifactFileStore.Session session, VerifiedDocument document) {
        try {
            return session.put(TEXT_DIRECTORY, document.textArtifactId() + ".txt", document.textUtf8());
        } catch (ArtifactStoreException error) {
            log.warn("document import text file failed: {} ({})", error.reason(), error.detail());
            throw new DocumentImportException(error.reason() == ArtifactStoreException.Reason.CONFLICT
                    ? DocumentImportFailure.ARTIFACT_FILE_CONFLICT : DocumentImportFailure.ARTIFACT_STORE_UNAVAILABLE);
        }
    }
}
