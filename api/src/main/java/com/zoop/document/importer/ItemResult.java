package com.zoop.document.importer;

import java.time.Instant;

import com.zoop.document.DocumentImportFailure;
import com.zoop.document.service.RegistrationOutcome.PointerResult;
import com.zoop.document.service.RegistrationOutcome.Presence;

/** What happened to one request item. Only identifiers and states; never text, paths or credentials. */
public sealed interface ItemResult {

    int index();

    /** The item's document version is registered and its transaction committed. */
    record Imported(int index, String documentId, String documentVersion, String textArtifactId, Presence article,
            Presence artifact, Presence artifactFile, Presence version, PointerResult pointer, String currentVersion,
            Instant collectedAt, String grantId, String grantRevision) implements ItemResult {
    }

    /**
     * The item failed and nothing of it is registered. {@code ingestionCode} is the S2-1 CLI's own code for a refused
     * export; {@code hasCurrentVersion} marks a lost compare-and-set, whose {@code currentVersion} (possibly null) is the
     * pointer the article actually has.
     */
    record Failed(int index, DocumentImportFailure failure, String ingestionCode, boolean hasCurrentVersion,
            String currentVersion) implements ItemResult {
    }

    /** An earlier item failed, so this one was not started. */
    record NotAttempted(int index) implements ItemResult {
    }
}
