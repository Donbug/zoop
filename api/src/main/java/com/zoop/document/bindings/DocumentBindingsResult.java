package com.zoop.document.bindings;

import com.zoop.document.bindings.DocumentBindingsExporter.Export;

/**
 * Outcome of one operator run: either the export that was written ({@code failure} null) or the code that stopped it. The
 * scope and whether a selection file was used are recorded either way, so an operator can read a result on its own.
 */
public record DocumentBindingsResult(DocumentBindingsScope scope, boolean selected, Export export,
        DocumentBindingsFailure failure) {

    public static DocumentBindingsResult succeeded(DocumentBindingsScope scope, boolean selected, Export export) {
        return new DocumentBindingsResult(scope, selected, export, null);
    }

    public static DocumentBindingsResult failed(DocumentBindingsScope scope, boolean selected,
            DocumentBindingsFailure failure) {
        return new DocumentBindingsResult(scope, selected, null, failure);
    }

    public boolean succeeded() {
        return failure == null;
    }
}
