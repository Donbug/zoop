package com.zoop.graph.version;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Clock;
import java.time.Instant;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/**
 * Pins the public graph version of one request (OpenAPI {@code publicationVersions}):
 * <ol>
 * <li>{@code round}: the version fixed when the briefing round was published (not available yet: no round store).</li>
 * <li>{@code asOf}: the version whose pointer change was the last one at or before that time. A given
 * {@code graphVersion} must equal it, otherwise 422.</li>
 * <li>{@code graphVersion} alone: only a version that was publicly active at some point.</li>
 * <li>nothing: the current active pointer, read once.</li>
 * </ol>
 * A missing version is 409 VERSION_UNAVAILABLE and is never replaced by the newest graph.
 */
@Component
public class GraphVersionSelector {
    private static final Pattern VERSION_ID = Pattern.compile("[A-Za-z0-9._:-]{1,120}");

    private final GraphVersionRepository repository;
    private final Clock clock;

    public GraphVersionSelector(GraphVersionRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    public SelectedGraphVersion select(String round, String graphVersion, Instant asOf) {
        Instant requestStart = clock.instant();
        if (graphVersion != null && !VERSION_ID.matcher(graphVersion).matches()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        if (round != null) {
            // Briefing rounds do not store a pinned graph version yet; never fall back to another version.
            throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
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
            if (!repository.everActivated(graphVersion)) throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
            return new SelectedGraphVersion(found(graphVersion), requestStart, false);
        }
        GraphVersionRecord active = repository.active()
                .orElseThrow(() -> new CustomException(ErrorCode.VERSION_UNAVAILABLE));
        return new SelectedGraphVersion(active, requestStart, false);
    }

    private GraphVersionRecord found(String versionId) {
        return repository.find(versionId).orElseThrow(() -> new CustomException(ErrorCode.VERSION_UNAVAILABLE));
    }
}
