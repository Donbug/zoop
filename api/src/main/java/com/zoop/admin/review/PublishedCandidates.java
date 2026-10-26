package com.zoop.admin.review;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Predicate;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.DisclosureExclusionReader;
import com.zoop.graph.read.EventDetailService;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionSelector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Which AI candidates users can see right now (#132 {@code onUserGraph}/{@code graphDb}). The active graph version's import
 * receipt keeps the AI source of every public relation ({@code sourceRefs}: S3 job and relation candidate) and of every public
 * issue ({@code sourceEvents}: S2 job and event candidate). An item counts as shown only when users can read it now: it is in the
 * snapshot after the current disclosure exclusions (the publication rules were applied at import) AND it passes the event
 * detail's read gates ({@link EvidenceService#shownNow}: article access, source grant, registry): a relation needs every evidence
 * it cites, an issue its head mentions ({@link EventDetailService#readable}). An item of the receipt that fails either is {@code excluded}: it was published and is hidden now.
 *
 * <p>Empty means it cannot be told: no active version, a synthetic fixture version (no receipt), an unreadable receipt or an
 * evidence gate that cannot be verified right now. The caller shows that as unknown, never as "not shown".
 *
 * <p>The answer is kept for {@link #TTL} per (active version, exclusion revision): the snapshot and receipt never change for a
 * version, but a source grant can expire with time, so the evidence gates are judged again at least that often.
 */
@Component
public class PublishedCandidates {
    static final Duration TTL = Duration.ofSeconds(60);
    private static final Logger log = LoggerFactory.getLogger(PublishedCandidates.class);
    private static final String IMPORTED = "snapshot";

    private final PublicGraphReader reader;
    private final EvidenceService receipts;
    private final GraphVersionSelector selector;
    private final DisclosureExclusionReader exclusions;
    private final Clock clock;
    private volatile Cached cached;

    private record Cached(String versionId, long exclusionRevision, Instant at, Shown shown) {
    }

    public PublishedCandidates(PublicGraphReader reader, EvidenceService receipts, GraphVersionSelector selector,
            DisclosureExclusionReader exclusions, Clock clock) {
        this.reader = reader;
        this.receipts = receipts;
        this.selector = selector;
        this.exclusions = exclusions;
        this.clock = clock;
    }

    /**
     * Keys {@code <jobId>\n<candidateId>}: S3 job and relation candidate, S2 job and event candidate. {@code excluded*} are the
     * receipt's sources whose public item users cannot read now.
     */
    public record Shown(String versionId, Set<String> relations, Set<String> events, Set<String> excludedRelations,
            Set<String> excludedEvents) {
        public boolean relation(String s3JobId, String relationCandidateId) {
            return relations.contains(key(s3JobId, relationCandidateId));
        }

        public boolean event(String s2JobId, String eventCandidateId) {
            return events.contains(key(s2JobId, eventCandidateId));
        }

        public boolean excludedRelation(String s3JobId, String relationCandidateId) {
            return excludedRelations.contains(key(s3JobId, relationCandidateId));
        }

        public boolean excludedEvent(String s2JobId, String eventCandidateId) {
            return excludedEvents.contains(key(s2JobId, eventCandidateId));
        }
    }

    static String key(String jobId, String candidateId) {
        return jobId + "\n" + candidateId;
    }

    public Optional<Shown> current(String requestId) {
        try {
            String activeId = selector.select(null, null, null, requestId).version().id();
            long revision = exclusions.current(activeId).revision();
            Cached hit = cached;
            if (fresh(hit, activeId, revision)) return Optional.of(hit.shown());
            // One reader computes; the others wait for its answer instead of gating the whole graph again in parallel.
            synchronized (this) {
                hit = cached;
                if (fresh(hit, activeId, revision)) return Optional.of(hit.shown());
                return compute(activeId, revision, requestId);
            }
        } catch (RuntimeException unavailable) {
            log.warn("published candidates unknown: {}", unavailable.getClass().getSimpleName());
            return Optional.empty();
        }
    }

    private boolean fresh(Cached hit, String activeId, long revision) {
        return hit != null && hit.versionId().equals(activeId) && hit.exclusionRevision() == revision
                && clock.instant().isBefore(hit.at().plus(TTL));
    }

    private Optional<Shown> compute(String activeId, long revision, String requestId) {
        Instant now = clock.instant();
        PublicGraphReader.Pinned pinned = reader.read(null, null, null, requestId);
        if (!IMPORTED.equals(pinned.selected().version().kind())) return Optional.empty();
        String versionId = pinned.selected().version().id();
        PublicGraphSnapshot snapshot = pinned.graph().snapshot();
        Obj bundle = receipts.graphImportBundle(versionId, requestId);
        // The event detail's evidence predicate: still in the filtered snapshot and readable now, asked once per id.
        Set<String> inSnapshot = new HashSet<>();
        snapshot.evidence().forEach(e -> inSnapshot.add(e.evidenceId()));
        Map<String, Boolean> judged = new HashMap<>();
        Predicate<String> shownNow = id -> inSnapshot.contains(id)
                && judged.computeIfAbsent(id, k -> receipts.shownNow(k, versionId, null, requestId));
        Set<String> relationIds = new HashSet<>();
        for (PublicGraphSnapshot.Relation r : snapshot.relations()) {
            if (r.evidenceIds().stream().allMatch(shownNow)) relationIds.add(r.relationId());
        }
        // An issue is shown when a direct read of it is (getEvent's head check), not only when every evidence still is.
        Set<String> issueIds = new HashSet<>();
        for (PublicGraphSnapshot.Issue i : snapshot.issues()) {
            if (EventDetailService.readable(bundle, i, shownNow)) issueIds.add(i.issueId());
        }
        Shown shown = read(bundle, versionId, relationIds, issueIds);
        // Keyed by what was actually read: an activation or exclusion between the two reads is caught next time.
        if (versionId.equals(activeId)) cached = new Cached(versionId, revision, now, shown);
        return Optional.of(shown);
    }

    /** Pure: the receipt bundle and the ids users can read now; every other receipt item is excluded. */
    static Shown read(Obj bundle, String versionId, Set<String> relationIds, Set<String> issueIds) {
        Set<String> relations = new HashSet<>();
        Set<String> excludedRelations = new HashSet<>();
        for (Obj relation : bundle.objects("relations")) {
            Set<String> into = relationIds.contains(relation.string("id")) ? relations : excludedRelations;
            for (Obj ref : relation.objects("sourceRefs")) {
                if ("s3-relation".equals(ref.string("kind"))) into.add(key(ref.string("jobId"), ref.string("id")));
            }
        }
        Set<String> events = new HashSet<>();
        Set<String> excludedEvents = new HashSet<>();
        for (Obj issue : bundle.objects("issues")) {
            Set<String> into = issueIds.contains(issue.string("id")) ? events : excludedEvents;
            for (Obj event : issue.objects("sourceEvents")) {
                if ("event-candidate".equals(event.string("kind"))) {
                    into.add(key(event.object("upstream").string("jobId"), event.string("ref")));
                }
            }
        }
        // One source behind a shown item and a hidden one at once is shown.
        excludedRelations.removeAll(relations);
        excludedEvents.removeAll(events);
        return new Shown(versionId, Set.copyOf(relations), Set.copyOf(events), Set.copyOf(excludedRelations),
                Set.copyOf(excludedEvents));
    }

    /** For a test or a caller holding JSON text. */
    static Shown read(String bundleJson, String versionId, Set<String> relationIds, Set<String> issueIds) {
        return read(StrictJson.parseObject(bundleJson), versionId, relationIds, issueIds);
    }
}
