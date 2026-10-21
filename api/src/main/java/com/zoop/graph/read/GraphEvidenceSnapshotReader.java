package com.zoop.graph.read;

import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.document.evidence.graph.GraphEvidenceReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;

/**
 * getEvidence's graph facts from the same pinned, filtered snapshot as getGraph. An evidence id is visible when the filtered
 * snapshot lists it AND either a visible issue or a visible relation still cites it (an excluded issue's evidence must not stay
 * readable just because the evidence list itself is unchanged), or, for a BASIS-ONLY span, a visible structural basis (verified by
 * asOf, relation not excluded) references the span's article version. {@code eventIds} are the visible issues that cite the id and
 * stay empty for a basis-only span, which carries the candidate {@link GraphEvidence.BasisRef}s instead: the snapshot does not
 * record which evidence a basis cites, so the service proves membership in the version's import receipt. The relation's own
 * evidence ids are never extended with basis evidence (that would leak a basis the asOf filter removed).
 */
@Component
public class GraphEvidenceSnapshotReader implements GraphEvidenceReader {
    private final PublicGraphReader reader;

    public GraphEvidenceSnapshotReader(PublicGraphReader reader) {
        this.reader = reader;
    }

    @Override
    public GraphEvidence read(String graphVersion, Instant asOf, String evidenceId) {
        PublicGraphReader.Pinned pinned = reader.read(null, graphVersion, asOf);
        PublicGraphSnapshot snapshot = pinned.graph().snapshot;
        String version = pinned.selected().version().id();
        Instant at = pinned.selected().asOf();
        Evidence span = snapshot.evidence().stream().filter(e -> e.evidenceId().equals(evidenceId)).findFirst().orElse(null);
        if (span == null) {
            return new GraphEvidence(version, at, null, List.of(), List.of());
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
            return new GraphEvidence(version, at, pinnedSpan, eventIds, List.of());
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
        if (refs.isEmpty()) {
            return new GraphEvidence(version, at, null, List.of(), List.of());
        }
        return new GraphEvidence(version, at, pinnedSpan, List.of(), refs.stream().distinct().toList());
    }
}
