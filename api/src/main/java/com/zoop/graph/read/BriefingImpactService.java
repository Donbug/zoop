package com.zoop.graph.read;

import java.util.*;
import com.zoop.briefing.impact.BriefingImpacts;
import com.zoop.briefing.impact.BriefingImpacts.*;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.response.Metadata;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.*;

/** Actual public HTTP read: pinned publication -> filtered graph -> registered receipt -> CURRENT evidence rights. */
@Service
public class BriefingImpactService {
    private final BriefingQueryService briefings;
    private final PublicGraphReader graphs;
    private final EvidenceService evidence;
    public BriefingImpactService(BriefingQueryService briefings, PublicGraphReader graphs, EvidenceService evidence) {
        this.briefings = briefings; this.graphs = graphs; this.evidence = evidence;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 10)
    public BriefingImpacts get(String roundId, String eventId, String graphVersion, String requestId) {
        var round = briefings.impactBasis(roundId, eventId, requestId);
        if (graphVersion != null && !graphVersion.equals(round.graphVersion()))
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        var metadata = new Metadata("s3_issue_impacts", round.windowTo(), round.graphVersion(), requestId, false, List.of());
        if (round.graphVersion() == null)
            return new BriefingImpacts(roundId, eventId, null, round.windowTo(), "unavailable", "publication_snapshot_not_recorded", List.of(), metadata);
        try {
            var pinned = graphs.read(roundId, round.graphVersion(), round.windowTo(), requestId);
            if (!round.graphVersion().equals(pinned.selected().version().id()) || pinned.selected().reconstructed())
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            var basis = pinned.selected().briefing();
            if (basis == null || !basis.roundId().equals(roundId) || !basis.issueCompanies().containsKey(eventId))
                throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            var graph = pinned.graph();
            if (!graph.issues.containsKey(eventId)) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            if (!"snapshot".equals(pinned.selected().version().kind()))
                return new BriefingImpacts(roundId, eventId, round.graphVersion(), round.windowTo(), "unavailable", "s3_receipt_not_recorded", List.of(), metadata);
            var relations = graph.snapshot.relations().stream().filter(r -> eventId.equals(r.source()) && "INVOLVES".equals(r.relationType())).toList();
            var bundle = evidence.graphImportBundle(round.graphVersion(), requestId);
            var rows = S3ImpactRows.read(bundle, relations);
            Map<String, EvidenceResponse> readable = new HashMap<>();
            Set<String> denied = new HashSet<>();
            // Checks relation membership as well as effect quotes. A revoked relation cannot leave its label behind.
            for (var relation : relations) for (String id : relation.evidenceIds())
                read(id, roundId, round.graphVersion(), round.windowTo().toString(), requestId, readable, denied);
            Set<String> visibleEvidence = new HashSet<>();
            graph.snapshot.evidence().forEach(e -> visibleEvidence.add(e.evidenceId()));
            List<CompanyImpact> companies = new ArrayList<>();
            for (String companyId : basis.issueCompanies().get(eventId)) {
                var company = graph.companies.get(companyId);
                if (company == null) throw new StrictJson.Malformed();
                List<Assessment> assessments = new ArrayList<>();
                for (var row : rows) {
                    if (!companyId.equals(row.companyId())) continue;
                    var relation = relations.stream().filter(r -> r.relationId().equals(row.relationId())).findFirst().orElseThrow(StrictJson.Malformed::new);
                    boolean permitted = relation.evidenceIds().stream().noneMatch(denied::contains);
                    List<EffectEvidence> quotes = new ArrayList<>();
                    for (var entry : row.effects().entrySet()) {
                        var citation = visibleEvidence.contains(entry.getKey())
                                ? read(entry.getKey(), roundId, round.graphVersion(), round.windowTo().toString(), requestId, readable, denied) : null;
                        if (citation == null) { permitted = false; continue; }
                        quotes.add(new EffectEvidence(citation.id(), entry.getValue(), citation.quote(), citation.articleId(), citation.articleVersion(),
                                citation.article().title(), citation.article().url(), citation.article().publishedAt(), citation.start(), citation.end()));
                    }
                    assessments.add(new Assessment(row.relationId() + ":" + Canonical.sha256(row.key()), row.relationId(),
                            permitted ? row.status() : "withheld", permitted ? row.label() : null, row.provenance(), permitted ? List.copyOf(quotes) : List.of()));
                }
                boolean available = assessments.stream().anyMatch(a -> "verified".equals(a.status()));
                companies.add(new CompanyImpact(companyId, company.label(), available ? "available" : "unavailable",
                        available ? null : assessments.isEmpty() ? "assessment_not_recorded" : "no_verified_assessment", List.copyOf(assessments)));
            }
            boolean available = companies.stream().anyMatch(c -> "available".equals(c.status()));
            return new BriefingImpacts(roundId, eventId, round.graphVersion(), round.windowTo(), available ? "available" : "unavailable",
                    available ? null : "no_verified_assessment", List.copyOf(companies), metadata);
        } catch (StrictJson.Malformed | org.springframework.dao.DataAccessException malformed) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    private EvidenceResponse read(String id, String round, String version, String at, String request,
            Map<String, EvidenceResponse> cache, Set<String> denied) {
        if (cache.containsKey(id)) return cache.get(id);
        if (denied.contains(id)) return null;
        try {
            var result = evidence.readImpactCitation(id, round, version, java.time.Instant.parse(at), request);
            if (result == null) { denied.add(id); return null; }
            if (!Boolean.TRUE.equals(result.quoteVerified()) || !version.equals(result.metadata().graphVersion()))
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            cache.put(id, result); return result;
        } catch (CustomException unavailable) {
            if (!Set.of(ErrorCode.EVIDENCE_UNAVAILABLE, ErrorCode.RESOURCE_NOT_FOUND).contains(unavailable.getErrorCode())) throw unavailable;
            denied.add(id); return null;
        }
    }
}
