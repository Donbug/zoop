package com.zoop.document.service;

import java.util.Optional;

/** ERD v6 {@code articles.kind}. The S2-1 source has no kind, so the operator declares it per item. */
public enum ArticleKind {
    NEWS("news"),
    DISCLOSURE("disclosure");

    private final String wire;

    ArticleKind(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static Optional<ArticleKind> fromWire(String value) {
        for (ArticleKind kind : values()) {
            if (kind.wire.equals(value)) {
                return Optional.of(kind);
            }
        }
        return Optional.empty();
    }
}
