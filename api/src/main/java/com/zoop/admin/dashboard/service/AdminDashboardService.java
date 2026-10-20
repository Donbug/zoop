package com.zoop.admin.dashboard.service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import com.zoop.admin.dashboard.dto.AdminDashboardResponse;
import com.zoop.admin.dashboard.dto.AdminDashboardResponse.DashboardAudit;
import com.zoop.admin.dashboard.dto.AdminDashboardResponse.DashboardError;
import com.zoop.admin.dashboard.dto.AdminDashboardResponse.DashboardGraph;
import com.zoop.admin.dashboard.dto.AdminDashboardResponse.DashboardLedger;
import com.zoop.admin.dashboard.dto.AdminDashboardResponse.DashboardMembers;
import com.zoop.admin.dashboard.repository.AdminDashboardRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.SectionFailure;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;

@Service
public class AdminDashboardService {
    private static final String UNAVAILABLE_MESSAGE = "이 영역의 원천 데이터를 아직 조회할 수 없습니다.";

    private final AdminDashboardRepository repository;
    private final Clock clock;

    public AdminDashboardService(AdminDashboardRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    public AdminDashboardResponse getDashboard(String requestId) {
        Instant generatedAt = clock.instant();
        List<SectionFailure> failures = new ArrayList<>();
        int successfulSourceReads = 0;

        DashboardMembers members = null;
        try {
            var counts = repository.memberCountsAt(generatedAt);
            members = new DashboardMembers(counts.registered(), counts.activeMemberSessions(),
                    counts.activeGuestSessions(), "zoop-db");
            successfulSourceReads++;
        } catch (DataAccessException exception) {
            failures.add(failure("members", generatedAt));
        }

        DashboardAudit audit = null;
        try {
            audit = new DashboardAudit(repository.auditCountBetween(generatedAt.minus(Duration.ofHours(24)), generatedAt));
            successfulSourceReads++;
        } catch (DataAccessException exception) {
            failures.add(failure("audit", generatedAt));
        }

        DashboardGraph graph = null;
        try {
            var summary = repository.graphSummaryAt(generatedAt);
            var active = summary.activeVersion().orElse(null);
            graph = new DashboardGraph(active == null ? null : active.id(),
                    active == null ? null : active.activatedAt(), summary.versionCount(), active,
                    null, null, null, null);
            successfulSourceReads++;
        } catch (DataAccessException exception) {
            failures.add(failure("graph", generatedAt));
        }

        if (successfulSourceReads == 0) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }

        failures.add(failure("ledger", generatedAt));
        failures.add(failure("candidates", generatedAt));
        failures.add(failure("jobs", generatedAt));
        failures.add(failure("ai", generatedAt));
        failures.add(failure("briefings", generatedAt));
        if (graph != null) {
            failures.add(failure("graph.review", generatedAt));
            failures.add(failure("graph.graphDb", generatedAt));
        }

        return AdminDashboardResponse.partial(generatedAt, requestId,
                new DashboardLedger("unavailable", new DashboardError("SOURCE_UNAVAILABLE", UNAVAILABLE_MESSAGE)),
                graph, members, audit, List.copyOf(failures));
    }

    private static SectionFailure failure(String section, Instant asOf) {
        return new SectionFailure(section, "SOURCE_UNAVAILABLE", UNAVAILABLE_MESSAGE, false, asOf);
    }
}
