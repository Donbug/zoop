package com.zoop.graph.read;

import com.zoop.briefing.impact.BriefingImpacts.Provenance;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.dto.CompanyIssueImpactAssessment;
import com.zoop.graph.read.dto.CompanyIssueImpactAssessment.Effects;
import com.zoop.graph.read.dto.CompanyIssueImpactAssessment.Result;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/** Reads only verified S3 quote effects from the selected public graph receipt. */
@Service
public class CompanyIssueImpactAssessmentService {
    private static final Logger log = LoggerFactory.getLogger(CompanyIssueImpactAssessmentService.class);
    private final PublicGraphReader graphs;
    private final EvidenceService evidence;

    public CompanyIssueImpactAssessmentService(PublicGraphReader graphs, EvidenceService evidence) {
        this.graphs = graphs;
        this.evidence = evidence;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 10)
    public CompanyIssueImpactAssessment get(String companyId, String issueId, String round, String graphVersion,
            String asOf, String requestId) {
        if (blank(companyId) || blank(issueId) || (round != null && round.isBlank())
                || (graphVersion != null && graphVersion.isBlank()))
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        Instant requestedAsOf = parseInstant(asOf);
        var pinned = graphs.read(round, graphVersion, requestedAsOf, requestId);
        var graph = pinned.graph();
        if (!graph.companies.containsKey(companyId) || !graph.issues.containsKey(issueId))
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);

        List<Relation> direct = graph.snapshot().relations().stream()
                .filter(r -> "INVOLVES".equals(r.relationType()) && issueId.equals(r.source()) && companyId.equals(r.target()))
                .toList();
        Metadata metadata = new Metadata("s3_issue_impacts", pinned.selected().asOf(),
                pinned.selected().version().id(), requestId, false, List.of());
        if (direct.isEmpty()) return unavailable(companyId, issueId, "no_public_path", metadata);
        if (pinned.selected().reconstructed() || !"snapshot".equals(pinned.selected().version().kind()))
            return unavailable(companyId, issueId, "not_recorded", metadata);

        try {
            var publication = evidence.graphPublication(pinned.selected().version().id(), requestId);
            List<S3ImpactRows.Row> rows = S3ImpactRows.read(publication, direct);
            if (rows.isEmpty()) return unavailable(companyId, issueId, "not_recorded", metadata);

            Map<String, Relation> relations = new HashMap<>();
            direct.forEach(r -> relations.put(r.relationId(), r));
            Set<String> visibleEvidence = graph.snapshot().evidence().stream()
                    .map(com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence::evidenceId)
                    .collect(java.util.stream.Collectors.toSet());
            Map<String, EvidenceResponse> citations = new HashMap<>();
            Set<String> denied = new HashSet<>();
            List<Result> results = new ArrayList<>();
            boolean evidenceUnavailable = false;
            Instant evidenceAsOf = pinned.selected().asOfRequested() ? pinned.selected().asOf() : null;
            for (S3ImpactRows.Row row : rows) {
                if (!"verified".equals(row.status())) continue;
                Relation relation = relations.get(row.relationId());
                if (relation == null || !companyId.equals(row.companyId())) throw new StrictJson.Malformed();
                boolean readable = true;
                for (String id : relation.evidenceIds())
                    readable &= read(id, round, pinned.selected().version().id(), evidenceAsOf, requestId, citations, denied) != null;
                for (String id : row.effects().keySet()) {
                    if (!visibleEvidence.contains(id)) {
                        readable = false;
                        continue;
                    }
                    readable &= read(id, round, pinned.selected().version().id(), evidenceAsOf, requestId, citations, denied) != null;
                }
                if (!readable) {
                    evidenceUnavailable = true;
                    break;
                }
                List<String> positive = effects(row, "positive");
                List<String> negative = effects(row, "negative");
                List<String> neutral = effects(row, "neutral");
                List<String> uncertain = effects(row, "uncertain");
                List<String> all = new ArrayList<>();
                all.addAll(positive); all.addAll(negative); all.addAll(neutral); all.addAll(uncertain);
                Provenance provenance = row.provenance();
                results.add(new Result(opaqueId(pinned.selected().version().id(), row.key()), "verified", row.label(), all,
                        new Effects(positive, negative, neutral, uncertain),
                        new CompanyIssueImpactAssessment.Provenance(provenance.sourceKind(), provenance.executionMode(), provenance.recordingKind())));
            }
            if (evidenceUnavailable) {
                Metadata partial = new Metadata(metadata.source(), metadata.asOf(), metadata.graphVersion(), requestId, true,
                        List.of(new SectionFailure("impact", "EVIDENCE_UNAVAILABLE",
                                "현재 공개 권한을 확인할 수 있는 영향 근거가 없습니다.", false, metadata.asOf())));
                return unavailable(companyId, issueId, "evidence_unavailable", partial);
            }
            return results.isEmpty() ? unavailable(companyId, issueId, "not_verified", metadata)
                    : new CompanyIssueImpactAssessment(companyId, issueId, "available", null, results, metadata);
        } catch (StrictJson.Malformed | org.springframework.dao.DataAccessException malformed) {
            log.warn("S3 impact assessment read failed (companyId={}, issueId={}, graphVersion={}, requestId={})",
                    companyId, issueId, pinned.selected().version().id(), requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    private EvidenceResponse read(String id, String round, String version, Instant at, String requestId,
            Map<String, EvidenceResponse> cache, Set<String> denied) {
        if (cache.containsKey(id)) return cache.get(id);
        if (denied.contains(id)) return null;
        try {
            EvidenceResponse citation = evidence.readImpactCitation(id, round, version, at, requestId);
            if (citation == null) { denied.add(id); return null; }
            if (!Boolean.TRUE.equals(citation.quoteVerified()) || !version.equals(citation.metadata().graphVersion()))
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            cache.put(id, citation);
            return citation;
        } catch (CustomException failure) {
            if (Set.of(ErrorCode.EVIDENCE_UNAVAILABLE, ErrorCode.RESOURCE_NOT_FOUND).contains(failure.getErrorCode())) {
                denied.add(id);
                return null;
            }
            throw failure;
        }
    }

    private static List<String> effects(S3ImpactRows.Row row, String side) {
        return row.effects().entrySet().stream().filter(e -> side.equals(e.getValue())).map(Map.Entry::getKey).sorted().toList();
    }

    private static String opaqueId(String version, String key) {
        return com.zoop.common.json.Canonical.sha256(version + "\n" + key);
    }

    private static CompanyIssueImpactAssessment unavailable(String companyId, String issueId, String reason, Metadata metadata) {
        return new CompanyIssueImpactAssessment(companyId, issueId, "unavailable", reason, List.of(), metadata);
    }

    private static boolean blank(String value) { return value == null || value.isBlank(); }

    private static Instant parseInstant(String value) {
        if (value == null) return null;
        try { return OffsetDateTime.parse(value).toInstant(); }
        catch (DateTimeException error) { throw new CustomException(ErrorCode.INVALID_REQUEST, error); }
    }
}
