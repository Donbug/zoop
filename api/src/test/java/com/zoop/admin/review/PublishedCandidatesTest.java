package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.admin.review.PublishedCandidates.Shown;
import java.util.Set;
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
}
