package com.zoop.admin.insights.entity;

import java.io.Serializable;
import java.util.Objects;

public class AdminInsightsCompanySnapshotRowId implements Serializable {
    private String snapshotId;
    private int ordinal;

    public AdminInsightsCompanySnapshotRowId() {
    }

    public AdminInsightsCompanySnapshotRowId(String snapshotId, int ordinal) {
        this.snapshotId = snapshotId;
        this.ordinal = ordinal;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) return true;
        if (!(other instanceof AdminInsightsCompanySnapshotRowId that)) return false;
        return ordinal == that.ordinal && Objects.equals(snapshotId, that.snapshotId);
    }

    @Override
    public int hashCode() {
        return Objects.hash(snapshotId, ordinal);
    }
}
