package com.zoop.document.bindings;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * The operator's explicit choice of document versions to bind ({@code zoop-document-bindings-selection-1}), in file order.
 * Every named version must be registered; the export refuses the whole run otherwise, it never binds a subset silently. A
 * version named twice is refused here, whoever builds the selection (the file parser or a later scheduler), because the AI
 * contract rejects a bindings file with a duplicate.
 */
public record BindingSelection(List<VersionKey> versions) {
    public BindingSelection {
        versions = List.copyOf(versions);
        Set<VersionKey> seen = new HashSet<>();
        for (VersionKey key : versions) {
            if (!seen.add(key)) {
                throw new DocumentBindingsException(DocumentBindingsFailure.SELECTION_INVALID);
            }
        }
    }

    /** One S2-1 document version: the app's article id and version are the same two values. */
    public record VersionKey(String documentId, String documentVersion) {
    }
}
