package com.zoop.admin.dashboard.dto;

import java.time.Instant;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.zoop.admin.jobs.AnalysisJobResponse.JobOut;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;

/** Read-only overview for A-ADM-01. Null sections are explained by metadata.failures. */
public record AdminDashboardResponse(Instant generatedAt, Metadata metadata,
        DashboardLedger ledger, DashboardGraph graph, JsonNode candidates, DashboardJobs jobs,
        JsonNode ai, JsonNode briefings, DashboardMembers members, DashboardAudit audit) {

    public record DashboardLedger(String status, DashboardError error) { }

    public record DashboardError(String code, String message) { }

    public record DashboardGraph(String activeVersionId, Instant activatedAt, long versionCount,
            DashboardActiveGraphVersion activeVersion, Long reviewRevision, Long reviewDecisions,
            List<JsonNode> rules, JsonNode graphDb) { }

    public record DashboardActiveGraphVersion(String id, long sequence, String kind, String sourceLabel,
            Instant createdAt, Instant activatedAt, long issueCount, long relationCount, long articleCount) { }

    public record DashboardMembers(long registered, long activeMemberSessions,
            long activeGuestSessions, String source) { }

    public record DashboardAudit(long last24h) { }

    public record DashboardJobs(long running, long queued, long failed24h, JobOut active, List<JobOut> recent) { }

    public static AdminDashboardResponse partial(Instant generatedAt, String requestId,
            DashboardLedger ledger, DashboardGraph graph, DashboardJobs jobs, DashboardMembers members, DashboardAudit audit,
            List<SectionFailure> failures) {
        return new AdminDashboardResponse(generatedAt,
                new Metadata("admin-dashboard", generatedAt, null, requestId, !failures.isEmpty(), failures),
                ledger, graph, null, jobs, null, null, members, audit);
    }
}
