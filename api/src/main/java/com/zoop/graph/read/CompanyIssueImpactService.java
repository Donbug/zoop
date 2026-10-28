package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.dto.ImpactPath;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/** Resolves an impact path only from an approved company-issue relation in one pinned public graph. */
@Service
public class CompanyIssueImpactService {
    private final PublicGraphReader reader;
    private final EvidenceService evidence;

    public CompanyIssueImpactService(PublicGraphReader reader, EvidenceService evidence) {
        this.reader = reader;
        this.evidence = evidence;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 5)
    public ImpactPath getImpact(String companyId, String issueId, String round, String graphVersion, String asOf,
            String requestId) {
        if (blank(companyId) || blank(issueId) || (round != null && round.isBlank())
                || (graphVersion != null && graphVersion.isBlank())) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        Instant requestedAsOf = parseInstant(asOf);
        PublicGraphReader.Pinned pinned = reader.read(round, graphVersion, requestedAsOf, requestId);
        DisplayGraph graph = pinned.graph();
        if (!graph.companies.containsKey(companyId) || !graph.issues.containsKey(issueId)) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }

        DisplayGraph.Edge direct = graph.edges.values().stream()
                .filter(edge -> !edge.derived() && "INVOLVES".equals(edge.relationType()))
                .filter(edge -> edge.source().equals(issueId) && edge.target().equals(companyId))
                .sorted(java.util.Comparator.comparing(DisplayGraph.Edge::id))
                .findFirst().orElse(null);
        boolean structuralRelation = direct == null && graph.edges.values().stream()
                .anyMatch(edge -> !edge.derived() && "STRUCTURALLY_RELATED_TO".equals(edge.relationType())
                        && (edge.source().equals(issueId) && edge.target().equals(companyId)
                                || edge.source().equals(companyId) && edge.target().equals(issueId)));
        Instant evidenceAsOf = pinned.selected().asOfRequested() ? pinned.selected().asOf() : null;
        List<String> visibleEvidenceIds = direct == null ? List.of() : direct.evidenceIds().stream()
                .filter(id -> evidence.shownNow(id, round, pinned.selected().version().id(), evidenceAsOf, requestId))
                .toList();
        List<ImpactPath.Step> steps = direct == null ? List.of() : List.of(
                new ImpactPath.Step(issueId, "issue", "기사에 기업과 사건의 연결이 기록되어 있습니다.", visibleEvidenceIds),
                new ImpactPath.Step(companyId, "company", direct.role() == null ? direct.summary() : direct.role(),
                        visibleEvidenceIds));
        boolean evidenceWithheld = direct != null && visibleEvidenceIds.size() != direct.evidenceIds().size();
        List<SectionFailure> failures = evidenceWithheld
                ? List.of(new SectionFailure("evidence", "EVIDENCE_UNAVAILABLE",
                        "현재 공개 권한을 확인할 수 있는 근거만 표시합니다.", false, pinned.selected().asOf()))
                : List.of();
        Metadata metadata = new Metadata(pinned.selected().source(), pinned.selected().asOf(),
                pinned.selected().version().id(), requestId, evidenceWithheld, failures);
        String pathStatus = direct != null ? "direct_available"
                : structuralRelation ? "structural_path_details_unavailable" : "no_direct_relation";
        return new ImpactPath(companyId, issueId, pathStatus, steps, metadata);
    }

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private static Instant parseInstant(String value) {
        if (value == null) return null;
        try {
            return OffsetDateTime.parse(value).toInstant();
        } catch (DateTimeException error) {
            throw new CustomException(ErrorCode.INVALID_REQUEST, error);
        }
    }
}
