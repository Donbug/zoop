package com.zoop.auth.entity;

import java.io.Serializable;
import java.util.Objects;

public class TermVersionId implements Serializable {
    private String termId;
    private String version;

    public TermVersionId() {
    }

    public TermVersionId(String termId, String version) {
        this.termId = termId;
        this.version = version;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof TermVersionId that)) {
            return false;
        }
        return Objects.equals(termId, that.termId)
            && Objects.equals(version, that.version);
    }

    @Override
    public int hashCode() {
        return Objects.hash(termId, version);
    }
}
