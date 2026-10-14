package com.zoop.auth.entity;

import java.io.Serializable;
import java.util.Objects;

public class TermAgreementId implements Serializable {
    private String memberId;
    private String termId;
    private String termVersion;

    public TermAgreementId() {
    }

    public TermAgreementId(String memberId, String termId, String termVersion) {
        this.memberId = memberId;
        this.termId = termId;
        this.termVersion = termVersion;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof TermAgreementId that)) {
            return false;
        }
        return Objects.equals(memberId, that.memberId)
            && Objects.equals(termId, that.termId)
            && Objects.equals(termVersion, that.termVersion);
    }

    @Override
    public int hashCode() {
        return Objects.hash(memberId, termId, termVersion);
    }
}
