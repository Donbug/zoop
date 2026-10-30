package com.zoop.document.bindings;

/**
 * Which registered article versions an export binds. A binding is identity, not a right: every reader of the bindings file
 * (the AI freeze, the app import) checks the current rights again, so {@link #ALL} is safe; {@link #AVAILABLE} simply does not
 * hand the AI runtime versions of withdrawn ({@code private}, {@code deleted}) articles it has no reason to see.
 */
public enum DocumentBindingsScope {
    /** Every version of every article whose {@code access_status} is {@code available} (the default). */
    AVAILABLE("available"),
    /** Every registered version, whatever the article's access status. */
    ALL("all");

    private final String wire;

    DocumentBindingsScope(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    /** The scope a setting names, or {@code null} for anything else (the caller decides how to fail). */
    public static DocumentBindingsScope parse(String value) {
        for (DocumentBindingsScope scope : values()) {
            if (scope.wire.equals(value)) {
                return scope;
            }
        }
        return null;
    }
}
