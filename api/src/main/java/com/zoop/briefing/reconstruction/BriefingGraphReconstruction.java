package com.zoop.briefing.reconstruction;

import com.zoop.briefing.storage.BriefingRound;
import com.zoop.common.json.Canonical;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.version.GraphVersionRecord;
import java.util.Optional;
import org.springframework.stereotype.Component;

/** Content-addressed sidecar of a preserved publication, never an activation or replacement of its graphVersion. */
@Component
public class BriefingGraphReconstruction {
    public static final String POLICY = "briefing-reconstruction-v1";
    public static final String KIND = "briefing_reconstruction";
    private final DocumentRegistryRepository registry;
    public BriefingGraphReconstruction(DocumentRegistryRepository registry) { this.registry = registry; }

    public static String id(BriefingRound row) {
        return "brf-reconstructed-" + Canonical.sha256(POLICY + "\n" + row.id() + "\n"
                + Canonical.sha256(Canonical.appBytes(row.payload())) + "\n"
                + Canonical.sha256(Canonical.appBytes(row.publicSnapshot())));
    }

    public Optional<com.zoop.graph.version.BriefingGraphLookup.Reconstruction> find(BriefingRound row) {
        return registry.findArtifact(id(row)).map(a -> {
            if (!"graph_snapshot".equals(a.kind()) || !"application/json".equals(a.mediaType()))
                throw new com.zoop.graph.snapshot.GraphSnapshotUnavailableException("snapshot_kind_mismatch");
            return new com.zoop.graph.version.BriefingGraphLookup.Reconstruction(new GraphVersionRecord(a.id(), 0, KIND, a.id(), a.storageUri(), a.sha256(), false), a.createdAt());
        });
    }
}
