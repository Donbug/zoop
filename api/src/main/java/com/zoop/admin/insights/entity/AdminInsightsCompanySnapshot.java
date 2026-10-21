package com.zoop.admin.insights.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** Durable aggregate snapshot backing stable, stateless company-insights cursors. */
@Entity
@Table(name = "admin_insights_company_snapshots")
public class AdminInsightsCompanySnapshot {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "window_name", nullable = false, columnDefinition = "text")
    private String windowName;

    @Column(name = "page_size", nullable = false)
    private int pageSize;

    @Column(name = "as_of", nullable = false, columnDefinition = "timestamptz")
    private Instant asOf;

    @Column(name = "total_companies", nullable = false)
    private long totalCompanies;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    @Column(name = "expires_at", nullable = false, columnDefinition = "timestamptz")
    private Instant expiresAt;

    protected AdminInsightsCompanySnapshot() {
    }
}
