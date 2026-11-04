package com.zoop.graph.read;

import com.zoop.common.request.ReadScope;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.SelectedGraphVersion;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.PublicationException;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.version.BriefingGraphUnavailableException;
import java.time.Instant;
import org.springframework.stereotype.Component;

/**
 * The one read path every public graph API shares: pin a version, load its immutable snapshot, apply the asOf filter
 * inside that version (only when asOf was requested) and the current exclusion overlay, then build the display graph.
 */
@Component
public class PublicGraphReader {
    private static final java.util.concurrent.atomic.AtomicLong INSTANCES = new java.util.concurrent.atomic.AtomicLong();
    /** Readers over different stores never share a request's kept snapshot. */
    private final String scopeKey = "public-graph:" + INSTANCES.incrementAndGet() + ":";
    private final GraphVersionSelector selector;
    private final GraphSnapshotStore store;
    private final DisclosureExclusionReader exclusions;
    private final GraphPublicationReader publications;
    private final GraphPublicationAuthority authority;

    public PublicGraphReader(GraphVersionSelector selector, GraphSnapshotStore store, DisclosureExclusionReader exclusions,
            GraphPublicationReader publications, GraphPublicationAuthority authority) {
        this.selector = selector;
        this.store = store;
        this.exclusions = exclusions;
        this.publications = publications;
        this.authority = authority;
    }

    /** One pinned version and what is publicly visible in it for this request. */
    public record Pinned(SelectedGraphVersion selected, DisplayGraph graph, DisclosureExclusions exclusions) {
        public Pinned(SelectedGraphVersion selected, DisplayGraph graph) {
            this(selected, graph, DisclosureExclusions.NONE);
        }
    }

    public Pinned read(String round, String graphVersion, Instant asOf) {
        return read(round, graphVersion, asOf, null);
    }

    public Pinned read(String round, String graphVersion, Instant asOf, String requestId) {
        return read(selector.select(round, graphVersion, asOf, requestId), requestId);
    }

    /** A version an earlier step of this read already pinned, kept as it was ({@link GraphVersionSelector#pinned}). */
    public Pinned readPinned(String versionId, Instant asOf, boolean asOfRequested) {
        return read(selector.pinned(versionId, asOf, asOfRequested), null);
    }

    /**
     * The verified snapshot and its publication, read once per version in one read-only request. Both are immutable for a
     * version id; the current authority (exclusions, article access, source grants, expiry) is not, so it is never kept.
     */
    private record Verified(PublicGraphSnapshot snapshot, GraphPublicationReader.Publication publication) { }

    private Verified verify(GraphVersionRecord version) {
        PublicGraphSnapshot snapshot = store.load(version);
        if (!"snapshot".equals(version.kind())) return new Verified(snapshot, null);
        try {
            return new Verified(snapshot, publications.read(version.id(), snapshot));
        } catch (PublicationException invalid) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false);
        }
    }

    private Pinned read(SelectedGraphVersion selected, String requestId) {
        Verified verified = ReadScope.memo(scopeKey + selected.version().id(), () -> verify(selected.version()));
        PublicGraphSnapshot snapshot = verified.snapshot();
        DisclosureExclusions currentExclusions = verified.publication() == null ? exclusions.current(selected.version().id())
                : authority.current(verified.publication(), requestId);
        PublicGraphSnapshot visible = GraphSnapshotFilter.apply(snapshot,
                selected.asOfRequested() ? selected.asOf() : null, currentExclusions,
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
        return new Pinned(selected, DisplayGraph.of(visible), currentExclusions);
    }
}
