package com.zoop.graph.version;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;

/**
 * Pins the public graph version of one request (OpenAPI {@code publicationVersions}):
 * <ol>
 * <li>{@code round}: the published briefing owner's fixed version and cutoff, after current read-authority checks.</li>
 * <li>{@code asOf}: the version whose pointer change was the last one at or before that time. A given
 * {@code graphVersion} must equal it, otherwise 422.</li>
 * <li>{@code graphVersion} alone: only a version that was publicly active at some point, read as of the moment it was first
 * published (its first activation), exactly as {@code asOf} at that moment with that version (#88): the version, the bases verified
 * by then, the articles published by then and the relation status at that time. The pinned time is returned as
 * {@code metadata.asOf}, so it can be sent back with the version and open the same view.</li>
 * <li>nothing: the current active pointer, read once.</li>
 * </ol>
 * A missing version is 409 VERSION_UNAVAILABLE and is never replaced by the newest graph.
 */
@Component
public class GraphVersionSelector {
    private static final Pattern VERSION_ID = Pattern.compile("[A-Za-z0-9._:-]{1,120}");

    private final GraphVersionRepository repository;
    private final Clock clock;
    private final BriefingGraphLookup briefings;

    public GraphVersionSelector(GraphVersionRepository repository, Clock clock) {
        this(repository, clock, (round, request) -> { throw new CustomException(ErrorCode.VERSION_UNAVAILABLE); });
    }

    @Autowired
    public GraphVersionSelector(GraphVersionRepository repository, Clock clock, BriefingGraphLookup briefings) {
        this.repository = repository;
        this.clock = clock;
        this.briefings = briefings;
    }

    public SelectedGraphVersion select(String round, String graphVersion, Instant asOf) {
        return select(round, graphVersion, asOf, null);
    }

    public SelectedGraphVersion select(String round, String graphVersion, Instant asOf, String requestId) {
        Instant requestStart = clock.instant();
        if (graphVersion != null && !VERSION_ID.matcher(graphVersion).matches()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        if (round != null) {
            var basis = briefings.resolve(round, requestId);
            if ((graphVersion != null && !graphVersion.equals(basis.graphVersion()))
                    || (asOf != null && !asOf.equals(basis.dataAsOf())))
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            if (basis.reconstruction() != null)
                return new SelectedGraphVersion(basis.reconstruction().version(), basis.dataAsOf(), true, basis);
            if (!repository.everActivated(basis.graphVersion()))
                throw new BriefingGraphUnavailableException("snapshot_unavailable");
            // A graph can be published after the input cutoff. Use the recorded version, not activeVersionIdAt(cutoff).
            var version = repository.find(basis.graphVersion())
                    .orElseThrow(() -> new BriefingGraphUnavailableException("snapshot_unavailable"));
            return new SelectedGraphVersion(version, basis.dataAsOf(), true, basis);
        }
        if (asOf != null) {
            String pinned = repository.activeVersionIdAt(asOf)
                    .orElseThrow(() -> new CustomException(ErrorCode.VERSION_UNAVAILABLE));
            if (graphVersion != null && !graphVersion.equals(pinned)) {
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            }
            return new SelectedGraphVersion(found(pinned), asOf, true);
        }
        if (graphVersion != null) {
            Instant first = repository.firstActivatedAt(graphVersion)
                    .orElseThrow(() -> new CustomException(ErrorCode.VERSION_UNAVAILABLE));
            GraphVersionRecord version = found(graphVersion);
            // Whole milliseconds, rounded up: clients keep millisecond times (a browser Date), and one just before the activation
            // would pick the version before it. Pinned only when sending it back with the version opens this version.
            Instant pinned = upToMillis(first);
            if (graphVersion.equals(repository.activeVersionIdAt(pinned).orElse(null))) {
                return new SelectedGraphVersion(version, pinned, true);
            }
            // Another pointer change in that same millisecond won it: no time opens this version, so read it as of the request.
            return new SelectedGraphVersion(version, requestStart, false);
        }
        GraphVersionRecord active = repository.active()
                .orElseThrow(() -> new CustomException(ErrorCode.VERSION_UNAVAILABLE));
        return new SelectedGraphVersion(active, requestStart, false);
    }

    static Instant upToMillis(Instant at) {
        Instant whole = at.truncatedTo(ChronoUnit.MILLIS);
        return whole.equals(at) ? at : whole.plusMillis(1);
    }

    private GraphVersionRecord found(String versionId) {
        return repository.find(versionId).orElseThrow(() -> new CustomException(ErrorCode.VERSION_UNAVAILABLE));
    }
}
