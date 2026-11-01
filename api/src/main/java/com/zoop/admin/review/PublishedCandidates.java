package com.zoop.admin.review;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Predicate;

import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.EventDetailService;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/** Active publication candidates after the shared current-rights overlay and source-local proof gates. */
@Component
public class PublishedCandidates {
    private static final Logger log = LoggerFactory.getLogger(PublishedCandidates.class);
    private static final String IMPORTED = "snapshot";

    private final PublicGraphReader reader;
    private final EvidenceService receipts;

    public PublishedCandidates(PublicGraphReader reader, EvidenceService receipts) {
        this.reader = reader;
        this.receipts = receipts;
    }

    /**
     * Keys {@code <jobId>\n<candidateId>}: S3 job and relation candidate, S2 job and event candidate. {@code excluded*} are the
     * receipt's sources whose public item users cannot read now.
     */
    public record Shown(String versionId, Set<String> relations, Set<String> events, Set<String> excludedRelations,
            Set<String> excludedEvents, Map<String, String> publicIssueIds) {
        public Shown(String versionId, Set<String> relations, Set<String> events, Set<String> excludedRelations,
                Set<String> excludedEvents) {
            this(versionId, relations, events, excludedRelations, excludedEvents, Map.of());
        }

        /**
         * The active version's public issue id for an AI snapshot event id (S2 {@code disposition.targetEventId}): the receipt
         * issue whose {@code sourceEvents} name it as a {@code snapshot-event}. Null when no issue, or more than one, does.
         */
        public String publicIssueId(String aiEventId) {
            return aiEventId == null ? null : publicIssueIds.get(aiEventId);
        }

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
            return compute(requestId);
        } catch (RuntimeException unavailable) {
            log.warn("published candidates unknown: {}", unavailable.getClass().getSimpleName());
            return Optional.empty();
        }
    }

    private Optional<Shown> compute(String requestId) {
        PublicGraphReader.Pinned pinned = reader.read(null, null, null, requestId);
        if (!IMPORTED.equals(pinned.selected().version().kind())) return Optional.empty();
        String versionId = pinned.selected().version().id();
        PublicGraphSnapshot snapshot = pinned.graph().snapshot();
        Publication publication = receipts.graphPublication(versionId, requestId);
        if (publication.contributions().stream().noneMatch(c -> "native".equals(c.sourceKind()))) return Optional.empty();
        // The event detail's evidence predicate: still in the filtered snapshot and readable now, asked once per id.
        Set<String> inSnapshot = new HashSet<>();
        snapshot.evidence().forEach(e -> inSnapshot.add(e.evidenceId()));
        Map<String, Boolean> judged = new HashMap<>();
        Predicate<String> shownNow = id -> inSnapshot.contains(id)
                && judged.computeIfAbsent(id, k -> receipts.shownNow(k, versionId, null, requestId));
        // An issue is shown when a direct read of it is (getEvent's head check), not only when every evidence still is.
        Set<String> issueIds = new HashSet<>();
        for (PublicGraphSnapshot.Issue i : snapshot.issues()) {
            if (EventDetailService.readable(publication, i, shownNow)) issueIds.add(i.issueId());
        }
        Set<String> relationIds = new HashSet<>();
        for (PublicGraphSnapshot.Relation r : snapshot.relations()) {
            if ((!publication.issueSources().containsKey(r.source()) || issueIds.contains(r.source()))
                    && (!publication.issueSources().containsKey(r.target()) || issueIds.contains(r.target()))
                    && r.evidenceIds().stream().allMatch(shownNow)) relationIds.add(r.relationId());
        }
        return Optional.of(read(publication, relationIds, issueIds, shownNow));
    }

    /** Source candidates retain their original identities while visibility follows the mapped public item. */
    static Shown read(Publication publication, Set<String> relationIds, Set<String> issueIds, Predicate<String> shownNow) {
        Set<String> relations = new HashSet<>();
        Set<String> excludedRelations = new HashSet<>();
        Set<String> events = new HashSet<>();
        Set<String> excludedEvents = new HashSet<>();
        Map<String, String> publicIssueIds = new HashMap<>();
        Set<String> ambiguous = new HashSet<>();
        for (var owners : publication.relationSources().values()) {
            var selected = publication.selectedRelationSources(owners.relationId());
            for (var ref : owners.sources()) {
                Set<String> into = excludedRelations;
                var source = publication.source(ref.sourceVersionId());
                if (!"native".equals(source.sourceKind())) continue;
                if (relationIds.contains(owners.relationId()) && selected.contains(ref)
                        && source.projection().relations().stream().filter(r -> ref.relationId().equals(r.relationId()))
                                .findFirst().orElseThrow().evidenceIds().stream().allMatch(shownNow)) into = relations;
                var relation = source.bundle().objects("relations").stream()
                        .filter(r -> ref.relationId().equals(r.string("id"))).findFirst().orElseThrow();
                for (var candidate : relation.objects("sourceRefs")) {
                    if ("s3-relation".equals(candidate.string("kind")))
                        into.add(key(candidate.string("jobId"), candidate.string("id")));
                }
            }
        }
        for (var owners : publication.issueSources().values()) {
            for (var ref : owners.members()) {
                var source = publication.source(ref.sourceVersionId());
                if (!"native".equals(source.sourceKind())) continue;
                var original = publication.originalIssue(ref);
                Set<String> into = issueIds.contains(owners.issueId())
                        && original.evidenceIds().stream().allMatch(shownNow)
                        && original.geographyEvidenceIds().stream().allMatch(shownNow) ? events : excludedEvents;
                var issue = source.bundle().objects("issues").stream()
                        .filter(i -> ref.issueId().equals(i.string("id"))).findFirst().orElseThrow();
                for (var event : issue.objects("sourceEvents")) {
                    if ("event-candidate".equals(event.string("kind"))) {
                        into.add(key(event.object("upstream").string("jobId"), event.string("ref")));
                    } else if ("snapshot-event".equals(event.string("kind"))) {
                        String previous = publicIssueIds.putIfAbsent(event.string("ref"), owners.issueId());
                        if (previous != null && !previous.equals(owners.issueId())) ambiguous.add(event.string("ref"));
                    }
                }
            }
        }
        ambiguous.forEach(publicIssueIds::remove);
        // One source behind a shown item and a hidden one at once is shown.
        excludedRelations.removeAll(relations);
        excludedEvents.removeAll(events);
        return new Shown(publication.versionId(), Set.copyOf(relations), Set.copyOf(events), Set.copyOf(excludedRelations),
                Set.copyOf(excludedEvents), Map.copyOf(publicIssueIds));
    }

}
