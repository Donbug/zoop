package com.zoop.graph.read;

import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;
import com.zoop.document.evidence.dto.EvidenceArticle;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.document.evidence.graph.GraphEvidenceReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

/**
 * getEvidence's graph facts from the same pinned, filtered snapshot as getGraph. An evidence id is visible when the filtered
 * snapshot lists it AND either a visible issue or a visible relation still cites it (an excluded issue's evidence must not stay
 * readable just because the evidence list itself is unchanged), or, for a span nothing visible cites directly, a visible
 * structural basis (verified by asOf, relation not excluded) or a visible INVOLVES relation references the span's article version.
 * {@code eventIds} are the visible issues that cite the id and stay empty for such a span, which carries the candidate
 * {@link GraphEvidence.BasisRef}s and {@link GraphEvidence.ImpactRef}s instead: the snapshot records neither which evidence a
 * basis cites nor any impact, so the service proves membership in the version's import receipt. The relation's own evidence ids
 * are never extended with basis or impact evidence (that would leak a basis or relation the asOf filter removed).
 */
@Component
public class GraphEvidenceSnapshotReader implements GraphEvidenceReader {
    private final PublicGraphReader reader;
    private final BriefingQueryService publications;
    private final BriefingRoundRepository rounds;

    public GraphEvidenceSnapshotReader(PublicGraphReader reader) {
        this(reader, null, null);
    }

    @org.springframework.beans.factory.annotation.Autowired
    public GraphEvidenceSnapshotReader(PublicGraphReader reader,
            BriefingQueryService publications,
            BriefingRoundRepository rounds) {
        this.reader = reader;
        this.publications = publications;
        this.rounds = rounds;
    }

    @Override
    public RoundRead readRound(String round, String graphVersion, Instant asOf, String evidenceId,
            String companyId, String requestId) {
        var pinned = reader.read(round, graphVersion, asOf, requestId);
        var selected = pinned.selected();
        var found = locate(pinned.graph().snapshot, selected.version().id(), selected.asOf(), evidenceId);
        if (!selected.reconstructed()) return new RoundRead(found, null);
        if (found.span() == null || publications == null)
            throw new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE);
        if (companyId != null && !pinned.graph().companies.containsKey(companyId))
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        // getItem rechecks current authority and exact stored citation/body/version. No fabricated graph import receipt.
        for (String event : found.eventIds()) {
            for (var citation : publications.getItem(round, event, requestId).path("evidence")) {
                if (!evidenceId.equals(citation.path("id").asString())) continue;
                var span = found.span();
                var saved = rounds.findItemEvidence(evidenceId).orElseThrow(() ->
                        new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE));
                if (span.start() != saved.start() || span.end() != saved.end()
                        || !span.articleId().equals(citation.path("documentId").asString())
                        || !span.articleVersion().equals(citation.path("documentVersion").asString()))
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                var article = new EvidenceArticle(citation.path("title").asString(),
                        citation.path("publisher").asString(), citation.path("url").asString(),
                        citation.path("publishedAt").isNull() ? null : Instant.parse(citation.path("publishedAt").asString()));
                var failures = companyId == null ? List.<SectionFailure>of()
                        : List.of(new SectionFailure("sentiment", "SOURCE_UNAVAILABLE",
                                "이 회차 근거에서 기업별 감성 판정을 제공하지 않습니다.", false, null));
                var response = new EvidenceResponse(evidenceId, citation.path("quote").asString(),
                        span.start(), span.end(), span.articleId(), span.articleVersion(), article, true, found.eventIds(),
                        new Metadata(selected.source(), selected.asOf(), selected.version().id(),
                                requestId, companyId != null, failures), null, span.articleVersion(), null, null, null, null);
                return new RoundRead(found, response);
            }
        }
        throw new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE);
    }

    @Override
    public GraphEvidence read(String graphVersion, Instant asOf, String evidenceId) {
        PublicGraphReader.Pinned pinned = reader.read(null, graphVersion, asOf);
        return locate(pinned.graph().snapshot, pinned.selected().version().id(), pinned.selected().asOf(), evidenceId);
    }

    /** The same facts from an already filtered snapshot; activation uses it for a version the selector cannot pin yet. */
    public static GraphEvidence locate(PublicGraphSnapshot snapshot, String version, Instant at, String evidenceId) {
        Evidence span = snapshot.evidence().stream().filter(e -> e.evidenceId().equals(evidenceId)).findFirst().orElse(null);
        if (span == null) {
            return new GraphEvidence(version, at, null, List.of(), List.of(), List.of());
        }
        GraphEvidence.Span pinnedSpan = new GraphEvidence.Span(span.articleId(), span.articleVersion(), span.start(), span.end());
        List<String> eventIds = new ArrayList<>();
        for (Issue issue : snapshot.issues()) {
            if (issue.evidenceIds().contains(evidenceId) || issue.geographyEvidenceIds().contains(evidenceId)) {
                eventIds.add(issue.issueId());
            }
        }
        boolean citedByRelation = snapshot.relations().stream().anyMatch(r -> r.evidenceIds().contains(evidenceId));
        if (!eventIds.isEmpty() || citedByRelation) {
            return new GraphEvidence(version, at, pinnedSpan, eventIds, List.of(), List.of());
        }
        List<GraphEvidence.BasisRef> refs = new ArrayList<>();
        for (Relation relation : snapshot.relations()) {
            if (!"STRUCTURALLY_RELATED_TO".equals(relation.relationType())) {
                continue;
            }
            for (Basis basis : relation.basis()) {
                boolean sameArticle = basis.articles().stream()
                        .anyMatch(a -> a.articleId().equals(span.articleId()) && a.articleVersion().equals(span.articleVersion()));
                if (sameArticle) {
                    refs.add(new GraphEvidence.BasisRef(relation.relationId(), relation.relationType(), relation.source(),
                            relation.target(), basis.basisId()));
                }
            }
        }
        // An INVOLVES relation of the filtered snapshot (its issue visible, every evidence id of it visible) whose own evidence cites
        // the same article version as the span: a candidate for a verifier-mapped impact quote, proven only by the receipt.
        Map<String, Evidence> spans = new HashMap<>();
        for (Evidence item : snapshot.evidence()) {
            spans.put(item.evidenceId(), item);
        }
        List<GraphEvidence.ImpactRef> impactRefs = new ArrayList<>();
        for (Relation relation : snapshot.relations()) {
            if (!"INVOLVES".equals(relation.relationType())) {
                continue;
            }
            boolean sameArticle = relation.evidenceIds().stream().map(spans::get).anyMatch(cited -> cited != null
                    && cited.articleId().equals(span.articleId()) && cited.articleVersion().equals(span.articleVersion()));
            if (sameArticle) {
                impactRefs.add(new GraphEvidence.ImpactRef(relation.relationId(), relation.relationType(), relation.source(),
                        relation.target()));
            }
        }
        if (refs.isEmpty() && impactRefs.isEmpty()) {
            return new GraphEvidence(version, at, null, List.of(), List.of(), List.of());
        }
        return new GraphEvidence(version, at, pinnedSpan, List.of(), refs.stream().distinct().toList(),
                impactRefs.stream().distinct().toList());
    }
}
