package com.zoop.graph.read;

import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.SelectedGraphVersion;
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
        SelectedGraphVersion selected = selector.select(round, graphVersion, asOf);
        PublicGraphSnapshot snapshot = store.load(selected.version());
        PublicGraphSnapshot visible = GraphSnapshotFilter.apply(snapshot,
                selected.asOfRequested() ? selected.asOf() : null, exclusions.current());
        return new Pinned(selected, DisplayGraph.of(visible));
    }
}
