package com.zoop.graph.read;

import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.SelectedGraphVersion;
import com.zoop.graph.version.BriefingGraphUnavailableException;
import java.time.Instant;
import org.springframework.stereotype.Component;

/**
 * The one read path every public graph API shares: pin a version, load its immutable snapshot, apply the asOf filter
 * inside that version (only when asOf was requested) and the current exclusion overlay, then build the display graph.
 */
@Component
public class PublicGraphReader {
    private final GraphVersionSelector selector;
    private final GraphSnapshotStore store;
    private final DisclosureExclusionReader exclusions;

    public PublicGraphReader(GraphVersionSelector selector, GraphSnapshotStore store, DisclosureExclusionReader exclusions) {
        this.selector = selector;
        this.store = store;
        this.exclusions = exclusions;
    }

    /** One pinned version and what is publicly visible in it for this request. */
    public record Pinned(SelectedGraphVersion selected, DisplayGraph graph) { }

    public Pinned read(String round, String graphVersion, Instant asOf) {
        return read(round, graphVersion, asOf, null);
    }

    public Pinned read(String round, String graphVersion, Instant asOf, String requestId) {
        return read(selector.select(round, graphVersion, asOf, requestId));
    }

    /** A version an earlier step of this read already pinned, kept as it was ({@link GraphVersionSelector#pinned}). */
    public Pinned readPinned(String versionId, Instant asOf, boolean asOfRequested) {
        return read(selector.pinned(versionId, asOf, asOfRequested));
    }

    private Pinned read(SelectedGraphVersion selected) {
        PublicGraphSnapshot snapshot = store.load(selected.version());
        PublicGraphSnapshot visible = GraphSnapshotFilter.apply(snapshot,
                selected.asOfRequested() ? selected.asOf() : null, exclusions.current(selected.version().id()),
                selected.briefing() != null && selected.briefing().reconstruction() != null);
        var basis = selected.briefing();
        if (basis != null) {
            if (!visible.issues().stream().map(PublicGraphSnapshot.Issue::issueId).toList().containsAll(basis.keyIssueIds())
                    || !visible.companies().stream().map(PublicGraphSnapshot.Company::companyId).toList().containsAll(basis.companyIds()))
                throw new BriefingGraphUnavailableException("briefing_targets_unavailable");
            for (var entry : basis.issueCompanies().entrySet()) {
                if (!visible.relations().stream().filter(r -> r.source().equals(entry.getKey())
                        && DisplayGraph.COMPANY_LINKS.contains(r.relationType())).map(PublicGraphSnapshot.Relation::target)
                        .toList().containsAll(entry.getValue()))
                    throw new BriefingGraphUnavailableException("briefing_targets_unavailable");
            }
            // Restrict the shared snapshot BEFORE deriving edges or serving any detail consumer.
            visible = GraphSnapshotFilter.briefing(visible, basis);
        }
        return new Pinned(selected, DisplayGraph.of(visible));
    }
}
