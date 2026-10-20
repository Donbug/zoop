package com.zoop.graph.read;

import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.document.evidence.graph.GraphEvidenceReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;

/**
 * getEvidence's graph facts from the same pinned, filtered snapshot as getGraph. An evidence id is visible only when the filtered
 * snapshot lists it AND a visible issue or a visible relation still cites it: an excluded issue's evidence must not stay readable
 * just because the evidence list itself is unchanged. {@code eventIds} are the visible issues that cite the id.
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
            return new GraphEvidence(version, at, null, List.of());
        }
        List<String> eventIds = new ArrayList<>();
        for (Issue issue : snapshot.issues()) {
            if (issue.evidenceIds().contains(evidenceId) || issue.geographyEvidenceIds().contains(evidenceId)) {
                eventIds.add(issue.issueId());
            }
        }
        boolean citedByRelation = snapshot.relations().stream().anyMatch(r -> r.evidenceIds().contains(evidenceId));
        if (eventIds.isEmpty() && !citedByRelation) {
            return new GraphEvidence(version, at, null, List.of());
        }
        return new GraphEvidence(version, at,
                new GraphEvidence.Span(span.articleId(), span.articleVersion(), span.start(), span.end()), eventIds);
    }
}
