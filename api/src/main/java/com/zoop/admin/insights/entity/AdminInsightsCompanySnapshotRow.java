package com.zoop.admin.insights.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;

/** One immutable company ranking result within an aggregate snapshot. */
@Entity
@Table(name = "admin_insights_company_snapshot_rows")
@IdClass(AdminInsightsCompanySnapshotRowId.class)
public class AdminInsightsCompanySnapshotRow {
    @Id
    @Column(name = "snapshot_id", nullable = false, columnDefinition = "text")
    private String snapshotId;

    @Id
    @Column(name = "ordinal", nullable = false)
    private int ordinal;

    @Column(name = "company_id", nullable = false, columnDefinition = "text")
    private String companyId;

    @Column(name = "name", nullable = false, columnDefinition = "text")
    private String name;

    @Column(name = "ticker", columnDefinition = "text")
    private String ticker;

    @Column(name = "watchlist_members", nullable = false)
    private long watchlistMembers;

    @Column(name = "holding_members", nullable = false)
    private long holdingMembers;

    @Column(name = "node_views", nullable = false)
    private long nodeViews;

    @Column(name = "ai_questions", nullable = false)
    private long aiQuestions;

    protected AdminInsightsCompanySnapshotRow() {
    }
}
