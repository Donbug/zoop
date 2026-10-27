package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.zoop.admin.review.PublishedCandidates.Shown;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.DisplayGraph;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.SelectedGraphVersion;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

class PublishedCandidatesTest {
    private static final String BUNDLE = """
            {"relations":[
              {"id":"edge-shown","sourceRefs":[{"kind":"s3-relation","jobId":"s3-a","id":"rc-1"}]},
              {"id":"edge-excluded","sourceRefs":[{"kind":"s3-relation","jobId":"s3-a","id":"rc-2"}]},
              {"id":"edge-follows","sourceRefs":[{"kind":"s2-comparison","jobId":"s2-a","id":"evc-1>event-1"}]}],
             "issues":[
              {"id":"issue-shown","sourceEvents":[{"upstream":{"jobId":"s2-a","inputDigest":"d"},"kind":"event-candidate","ref":"evc-1"},
                                                   {"upstream":{"jobId":"s2-a","inputDigest":"d"},"kind":"snapshot-event","ref":"event-1"}]},
              {"id":"issue-excluded","sourceEvents":[{"upstream":{"jobId":"s2-a","inputDigest":"d"},"kind":"event-candidate","ref":"evc-2"}]}]}""";

    @Test
    void onlyItemsTheFilteredSnapshotStillShowsCountAndOnlyTheirCandidateSources() {
        Shown shown = PublishedCandidates.read(BUNDLE, "v1", Set.of("edge-shown", "edge-follows"), Set.of("issue-shown"));

        assertTrue(shown.relation("s3-a", "rc-1"));
        assertFalse(shown.relation("s3-a", "rc-2"), "an excluded relation's source is not shown");
        assertTrue(shown.event("s2-a", "evc-1"));
        assertFalse(shown.event("s2-a", "evc-2"), "an excluded issue's event candidate is not shown");
        assertFalse(shown.event("s2-a", "event-1"), "a snapshot event is not a candidate");
        assertFalse(shown.relation("s3-b", "rc-1"), "the job is part of the key");
        assertEquals(1, shown.relations().size(), "an s2-comparison reference is not an S3 relation");
        assertTrue(shown.excludedRelation("s3-a", "rc-2"), "published in the version and hidden now");
        assertTrue(shown.excludedEvent("s2-a", "evc-2"));
        assertFalse(shown.excludedRelation("s3-a", "rc-1"));
        assertFalse(shown.excludedRelation("s3-a", "rc-9"), "never in the version: not excluded, just not stored");
    }

    @Test
    void anAiSnapshotEventMapsToTheOneReceiptIssueThatNamesIt() {
        String bundle = """
                {"relations":[],"issues":[
                  {"id":"issue:a-2026q3","sourceEvents":[{"upstream":{"jobId":"s2-a","inputDigest":"d"},"kind":"snapshot-event","ref":"event-a"},
                                                         {"upstream":{"jobId":"s2-b","inputDigest":"d"},"kind":"snapshot-event","ref":"event-a"}]},
                  {"id":"issue:b-2026q3","sourceEvents":[{"upstream":{"jobId":"s2-a","inputDigest":"d"},"kind":"snapshot-event","ref":"event-both"},
                                                         {"upstream":{"jobId":"s2-a","inputDigest":"d"},"kind":"event-candidate","ref":"evc-1"}]},
                  {"id":"issue:c-2026q3","sourceEvents":[{"upstream":{"jobId":"s2-a","inputDigest":"d"},"kind":"snapshot-event","ref":"event-both"}]}]}""";
        Shown shown = PublishedCandidates.read(bundle, "v1", Set.of(), Set.of());

        assertEquals("issue:a-2026q3", shown.publicIssueId("event-a"), "the AI event id the S2 disposition targets");
        assertNull(shown.publicIssueId("event-both"), "two public issues: which one cannot be told");
        assertNull(shown.publicIssueId("evc-1"), "an event candidate is not an existing event");
        assertNull(shown.publicIssueId("event-unknown"), "not in the active version");
        assertNull(shown.publicIssueId(null));
    }

    @Test
    void anExpiredAnswerIsServedWhileOneReaderRecomputesItButAnotherVersionIsWaitedFor() throws Exception {
        AtomicReference<Instant> now = new AtomicReference<>(Instant.parse("2026-10-27T00:00:00Z"));
        Clock clock = new Clock() {
            public ZoneId getZone() { return ZoneId.of("UTC"); }
            public Clock withZone(ZoneId zone) { return this; }
            public Instant instant() { return now.get(); }
        };
        AtomicReference<String> active = new AtomicReference<>("v1");
        GraphVersionSelector selector = mock(GraphVersionSelector.class);
        when(selector.select(any(), any(), any(), any())).thenAnswer(call -> selected(active.get()));
        CountDownLatch computing = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger reads = new AtomicInteger();
        PublicGraphReader reader = mock(PublicGraphReader.class);
        when(reader.read(any(), any(), any(), any())).thenAnswer(call -> {
            if (reads.incrementAndGet() == 2) {
                computing.countDown();
                assertTrue(release.await(10, TimeUnit.SECONDS));
            }
            String id = active.get();
            return new PublicGraphReader.Pinned(selected(id),
                    DisplayGraph.of(new PublicGraphSnapshot(1, id, "b", List.of(), List.of(), List.of(), List.of(), List.of())));
        });
        EvidenceService receipts = mock(EvidenceService.class);
        when(receipts.graphImportBundle(any(), any())).thenReturn(StrictJson.parseObject("{\"relations\":[],\"issues\":[]}"));
        PublishedCandidates published = new PublishedCandidates(reader, receipts, selector, v -> DisclosureExclusions.NONE, clock);

        assertEquals("v1", published.current("r-1").orElseThrow().versionId());
        now.set(now.get().plus(PublishedCandidates.TTL).plus(Duration.ofSeconds(1)));
        CompletableFuture<Shown> recomputing = CompletableFuture.supplyAsync(() -> published.current("r-2").orElseThrow());
        assertTrue(computing.await(10, TimeUnit.SECONDS));
        // The same version and exclusion revision: the expired answer at once, never a wait on the whole-graph gate.
        Shown meanwhile = CompletableFuture.supplyAsync(() -> published.current("r-3").orElseThrow()).get(5, TimeUnit.SECONDS);
        assertEquals("v1", meanwhile.versionId());
        assertEquals(2, reads.get(), "only one reader recomputes");

        // Another active version is never answered from the old one: it waits for the computation.
        active.set("v2");
        CompletableFuture<Shown> otherVersion = CompletableFuture.supplyAsync(() -> published.current("r-4").orElseThrow());
        Thread.sleep(200);
        assertFalse(otherVersion.isDone(), "a new version waits instead of reading the old version's answer");
        release.countDown();
        recomputing.get(10, TimeUnit.SECONDS);
        assertEquals("v2", otherVersion.get(10, TimeUnit.SECONDS).versionId());
    }

    private static SelectedGraphVersion selected(String id) {
        return new SelectedGraphVersion(new GraphVersionRecord(id, 1, "snapshot", "artifact-" + id, "uri", "a".repeat(64), true),
                Instant.parse("2026-10-27T00:00:00Z"), false);
    }
}
