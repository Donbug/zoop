package com.zoop.briefing.query;

import com.zoop.briefing.replay.BriefingReplayReadPolicy;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.version.BriefingGraphLookup;
import com.zoop.graph.version.BriefingGraphUnavailableException;
import java.util.LinkedHashMap;
import java.util.List;
import org.springframework.stereotype.Component;

/** Both direct round graph reads and the briefing basis endpoint use the publication's current authority. */
@Component
public final class PublishedBriefingGraphLookup implements BriefingGraphLookup {
    private final BriefingRoundRepository repository;
    private final BriefingContentAccess access;
    private final BriefingReplayReadPolicy replay;
    private final com.zoop.briefing.reconstruction.BriefingGraphReconstruction reconstructions;

    public PublishedBriefingGraphLookup(BriefingRoundRepository repository, BriefingContentAccess access,
            BriefingReplayReadPolicy replay) {
        this(repository, access, replay, null);
    }

    @org.springframework.beans.factory.annotation.Autowired
    public PublishedBriefingGraphLookup(BriefingRoundRepository repository, BriefingContentAccess access,
            BriefingReplayReadPolicy replay, com.zoop.briefing.reconstruction.BriefingGraphReconstruction reconstructions) {
        this.repository = repository;
        this.access = access;
        this.replay = replay;
        this.reconstructions = reconstructions;
    }

    @Override
    public Basis resolve(String roundId, String requestId) {
        try {
            return read(roundId, requestId);
        } catch (org.springframework.dao.DataAccessException | IllegalArgumentException | java.time.DateTimeException | com.zoop.common.json.StrictJson.Malformed error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, error);
        }
    }

    private Basis read(String roundId, String requestId) {
        if (roundId == null || roundId.isBlank() || roundId.length() > 256)
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        var row = repository.findById(roundId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        if (row.publishedAt() == null || !"published".equals(row.status()))
            throw new BriefingGraphUnavailableException("round_not_available");
        boolean localReplay = BriefingReplayReadPolicy.marked(row);
        if ((localReplay && !replay.permits(row)) || !access.mayRead(row, requestId == null ? "round-graph" : requestId))
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        var reconstructed = row.graphVersion() == null && localReplay && reconstructions != null
                ? reconstructions.find(row).orElse(null) : null;
        if (row.graphVersion() == null && reconstructed == null)
            throw new BriefingGraphUnavailableException("snapshot_not_recorded");
        BriefingSnapshotValidator.validate(row, localReplay && replay.permits(row));
        if (reconstructed != null) {
            for (var item : row.payload().path("items"))
                BriefingItemDetailValidator.validate(row, item,
                        row.publicSnapshot().path("itemDetails").path(item.path("eventId").asString()), repository);
        }
        var targets = new LinkedHashMap<String, List<String>>();
        row.payload().path("items").forEach(item -> {
            var companies = new java.util.ArrayList<String>();
            item.path("companies").forEach(company -> companies.add(company.path("id").asString()));
            targets.put(item.path("eventId").asString(), companies);
        });
        return new Basis(row.id(), reconstructed == null ? row.graphVersion() : reconstructed.version().id(),
                row.windowTo(), targets, reconstructed);
    }
}
