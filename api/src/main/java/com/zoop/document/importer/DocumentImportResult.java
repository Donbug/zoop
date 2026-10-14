package com.zoop.document.importer;

import java.util.List;

import com.zoop.document.DocumentImportFailure;

/**
 * Outcome of one operator run. {@code requestFailure} is set when the request as a whole could not run (invalid request
 * or busy store); otherwise {@code items} has one entry per request item, in order, and the run failed exactly when one
 * of them is {@link ItemResult.Failed}. Items before the first failure are committed and say so explicitly.
 */
public record DocumentImportResult(DocumentImportFailure requestFailure, List<ItemResult> items) {

    public static DocumentImportResult requestFailed(DocumentImportFailure failure, List<ItemResult> items) {
        return new DocumentImportResult(failure, List.copyOf(items));
    }

    public boolean succeeded() {
        return requestFailure == null && items.stream().noneMatch(item -> item instanceof ItemResult.Failed);
    }

    /** The code that decided the exit status: the request-level failure or the first failed item's. */
    public DocumentImportFailure firstFailure() {
        if (requestFailure != null) {
            return requestFailure;
        }
        return items.stream().filter(item -> item instanceof ItemResult.Failed).map(item -> ((ItemResult.Failed) item).failure())
                .findFirst().orElse(null);
    }
}
