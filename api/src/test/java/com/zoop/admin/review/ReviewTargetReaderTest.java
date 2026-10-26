package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.zoop.admin.review.ReviewTargetReader.Projection;
import com.zoop.admin.review.ReviewTargetReader.Row;
import com.zoop.common.json.StrictJson.Malformed;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;

class ReviewTargetReaderTest {
    static final String EVENT_A = "evc-" + "a".repeat(64);
    static final String EVENT_B = "evc-" + "b".repeat(64);
    static final String EVENT_HELD = "evc-" + "c".repeat(64);
    static final String EVENT_REJECTED = "evc-" + "d".repeat(64);

    static String rel(char c) {
        return "rc-" + String.valueOf(c).repeat(64);
    }

    static String event(String id, String state, String disposition, String... companies) {
        String participants = java.util.Arrays.stream(companies)
                .map(company -> "{\"companyId\":\"" + company + "\",\"name\":\"n\",\"role\":\"subject\"}")
                .collect(Collectors.joining(",", "[", "]"));
        return """
                {"eventCandidateId":"%s","state":"%s","disposition":{"status":"%s"},
                 "mention":{"title":"t","participants":%s}}""".formatted(id, state, disposition, participants);
    }

    static String s2(String... events) {
        return "{\"eventCandidates\":[" + String.join(",", events) + "]}";
    }

    static String endpoint(String kind, String ref) {
        return "{\"kind\":\"" + kind + "\",\"ref\":\"" + ref + "\"}";
    }

    static String relation(String id, String type, String subject, String object, String status, String revision) {
        return """
                {"relationCandidateId":"%s","sourceRevision":"%s","type":"%s","subject":%s,"object":%s,
                 "eligibility":{"status":"%s"}}""".formatted(id, revision, type, subject, object, status);
    }

    static String s3(String... relations) {
        return "{\"relations\":[" + String.join(",", relations) + "]}";
    }

    static Map<String, Row> byKey(Projection projection) {
        return projection.rows().stream().collect(Collectors.toMap(r -> r.type() + ":" + r.externalId(), Function.identity()));
    }

    @Test
    void oneCandidatePerEventCandidateWithTheRelationsThatNameIt() {
        Projection projection = ReviewTargetReader.read(
                s2(event(EVENT_A, "candidate", "new-event-candidate", "SK", "NV")),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "SK"), endpoint("event", EVENT_A), "eligible", "1"),
                        relation(rel('2'), "PARTICIPATES_IN", endpoint("company", "SS"), endpoint("event", EVENT_A), "hold", "2")));

        Map<String, Row> rows = byKey(projection);
        assertEquals(3, rows.size());
        Row candidate = rows.get("candidate:" + EVENT_A);
        assertEquals(EVENT_A, candidate.candidateId());
        assertEquals("HOLD", candidate.status(), "a HOLD relation keeps the candidate under review");
        assertEquals(List.of("NV", "SK", "SS"), candidate.companyIds(), "participants and relation companies");
        assertEquals(List.of("PARTICIPATES_IN"), candidate.relationTypes());
        assertEquals("3", candidate.sourceRevision(), "the sum of its relations' revisions");
        assertEquals(new Row("relation", rel('2'), EVENT_A, "HOLD", List.of("SS"), List.of("PARTICIPATES_IN"), "2"),
                rows.get("relation:" + rel('2')));
        assertEquals("ALLOW", rows.get("relation:" + rel('1')).status());
        assertEquals(0, projection.unknownEvents());
    }

    @Test
    void aRelationWithoutAnEventIsACandidateOfItsOwn() {
        Map<String, Row> rows = byKey(ReviewTargetReader.read(s2(),
                s3(relation(rel('1'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "4"))));

        assertEquals(new Row("candidate", rel('1'), rel('1'), "HOLD", List.of("A", "B"), List.of("SUPPLIES"), "4"),
                rows.get("candidate:" + rel('1')));
        assertEquals(rel('1'), rows.get("relation:" + rel('1')).candidateId());
    }

    @Test
    void heldOrRejectedEventCandidatesAreLeftOutWithTheirRelations() {
        Projection projection = ReviewTargetReader.read(
                s2(event(EVENT_HELD, "candidate", "held", "A"), event(EVENT_REJECTED, "rejected", "new-event-candidate", "A")),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_HELD), "hold", "1"),
                        relation(rel('2'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_REJECTED), "hold", "1")));

        assertEquals(List.of(), projection.rows());
        assertEquals(0, projection.unknownEvents(), "a known but held event is not an unknown one");
    }

    @Test
    void anEventOutsideTheUpstreamResultIsCountedAndKeptAlone() {
        Projection projection = ReviewTargetReader.read(s2(),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", "event-1"), "hold", "1")));

        assertEquals(1, projection.unknownEvents());
        assertEquals(List.of("A"), byKey(projection).get("candidate:" + rel('1')).companyIds());
    }

    @Test
    void pendingRelationsWaitForAVerdict() {
        Projection projection = ReviewTargetReader.read(s2(event(EVENT_A, "candidate", "new-event-candidate")),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_A), "pending", "0")));

        assertEquals(List.of(), projection.rows(), "no candidate row without a decided relation");
    }

    @Test
    void candidateStatusFallsBackToAllowThenReject() {
        Map<String, Row> rows = byKey(ReviewTargetReader.read(
                s2(event(EVENT_A, "candidate", "new-event-candidate"), event(EVENT_B, "candidate", "same-event-candidate")),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_A), "eligible", "1"),
                        relation(rel('2'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_A), "reject", "1"),
                        relation(rel('3'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_B), "reject", "1"))));

        assertEquals("ALLOW", rows.get("candidate:" + EVENT_A).status());
        assertEquals("REJECT", rows.get("candidate:" + EVENT_B).status());
    }

    @Test
    void anUnreadableDocumentWritesNothing() {
        String good = relation(rel('1'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "1");
        assertThrows(Malformed.class, () -> ReviewTargetReader.read("{}", s3(good)));
        assertThrows(Malformed.class, () -> ReviewTargetReader.read(s2(), s3(good.replace("\"hold\"", "\"maybe\""))));
        assertThrows(Malformed.class, () -> ReviewTargetReader.read(s2(), s3(good.replace(rel('1'), "rc-short"))));
        assertThrows(Malformed.class, () -> ReviewTargetReader.read(s2(), s3(good.replace("\"company\"", "\"person\""))));
        assertThrows(Malformed.class, () -> ReviewTargetReader.read(
                s2(event(EVENT_A, "candidate", "x"), event(EVENT_A, "candidate", "x")), s3(good)), "duplicate event id");
    }
}
