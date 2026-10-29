package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
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
                {"eventCandidateId":"%s","state":"%s","disposition":{"status":"%s","targetEventId":null},
                 "mention":{"mentionId":"m-1","title":"t","action":"a","target":null,"eventTime":"2026-10-20",
                  "period":null,"assertionStatus":"announced","background":false,"countries":[],"keywords":[],
                  "participants":%s},
                 "citations":[{"documentId":"doc-%s","documentVersion":"%s","start":0,"end":3,"quote":"q"}]}"""
                .formatted(id, state, disposition, participants, "1".repeat(64), "2".repeat(64));
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
                 "eligibility":{"status":"%s","reasons":[{"code":"claim_%s"}]},
                 "citations":[{"documentId":"doc-%s","documentVersion":"%s","start":0,"end":2,"quote":"r"}]}"""
                .formatted(id, revision, type, subject, object, status, status, "1".repeat(64), "2".repeat(64));
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
        Row hold = rows.get("relation:" + rel('2'));
        assertEquals(List.of(EVENT_A, "HOLD", List.of("SS"), List.of("PARTICIPATES_IN"), "2"),
                List.of(hold.candidateId(), hold.status(), hold.companyIds(), hold.relationTypes(), hold.sourceRevision()));
        assertEquals("ALLOW", rows.get("relation:" + rel('1')).status());
        assertEquals(0, projection.unknownEvents());
    }

    @Test
    void theListDisplayComesFromTheEventCandidateAndItsRelations() {
        Map<String, Row> rows = byKey(ReviewTargetReader.read(
                s2(event(EVENT_A, "candidate", "new-event-candidate", "SK")),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "SK"), endpoint("event", EVENT_A), "hold", "1"),
                        relation(rel('2'), "PARTICIPATES_IN", endpoint("company", "SS"), endpoint("event", EVENT_A), "reject", "1"))));

        ReviewTargetReader.Display candidate = rows.get("candidate:" + EVENT_A).display();
        assertEquals(new ReviewTargetReader.Display(null, "t", "a", null, "2026-10-20", 1,
                List.of(new ReviewTargetReader.Company("SK", "n", "subject"), new ReviewTargetReader.Company("SS", "SS", null)),
                List.of("claim_hold", "claim_reject")), candidate, "the mention's own citations count, every relation's reasons");
        ReviewTargetReader.Display relation = rows.get("relation:" + rel('2')).display();
        assertEquals(new ReviewTargetReader.Display(null, null, null, null, null, 1,
                List.of(new ReviewTargetReader.Company("SS", "SS", null)), List.of("claim_reject")), relation);
    }

    @Test
    void aRelationWithoutAnEventIsACandidateOfItsOwn() {
        Map<String, Row> rows = byKey(ReviewTargetReader.read(s2(),
                s3(relation(rel('1'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "4"))));

        Row alone = rows.get("candidate:" + rel('1'));
        assertEquals(List.of(rel('1'), "HOLD", List.of("A", "B"), List.of("SUPPLIES"), "4"),
                List.of(alone.candidateId(), alone.status(), alone.companyIds(), alone.relationTypes(), alone.sourceRevision()));
        assertEquals(null, alone.display().title(), "no event: no title, action or event time");
        assertEquals(1, alone.display().evidenceCount(), "the relation's own citations");
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
    void onlyAnOperatorsFinalApprovalMarksARelationApproved() {
        String automatic = relation(rel('1'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "eligible", "1")
                .replace("\"reasons\":", "\"approvalBasis\":{\"kind\":\"automatic-verifier\"},\"reasons\":");
        String operator = relation(rel('2'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "C"), "eligible", "3")
                .replace("\"reasons\":", "\"approvalBasis\":{\"kind\":\"operator-final-approval\"},\"reasons\":");
        Map<String, Row> rows = byKey(ReviewTargetReader.read(s2(), s3(automatic, operator)));

        assertEquals(false, rows.get("relation:" + rel('1')).operatorApproved());
        assertEquals(true, rows.get("relation:" + rel('2')).operatorApproved());
        assertEquals(null, rows.get("candidate:" + rel('2')).operatorApproved(), "a candidate row carries no approval");
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
    void onlyAMissingArrayRefusesTheWholeDocument() {
        String good = relation(rel('1'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "1");
        assertThrows(Malformed.class, () -> ReviewTargetReader.read("{}", s3(good)));
        assertThrows(Malformed.class, () -> ReviewTargetReader.read(s2(), "{}"));
    }

    @Test
    void anUnreadableRelationIsLeftOutAndTheRestOfTheJobIsKept() {
        String good = relation(rel('1'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "1");
        Projection projection = ReviewTargetReader.read(s2(), s3(good,
                relation(rel('2'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "maybe", "1"),
                relation("rc-short", "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "1"),
                relation(rel('3'), "SUPPLIES", endpoint("person", "A"), endpoint("company", "B"), "hold", "1"),
                "42"));

        assertEquals(4, projection.skipped());
        assertEquals(List.of(rel('1'), rel('1')), projection.rows().stream().map(Row::externalId).toList());
    }

    @Test
    void anUnreadableEventKeepsItsRelationsOut() {
        String broken = "{\"eventCandidateId\":\"" + EVENT_A + "\",\"state\":\"candidate\"}";
        Projection projection = ReviewTargetReader.read(s2(broken, event(EVENT_B, "candidate", "x", "A")),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_A), "hold", "1"),
                        relation(rel('2'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_B), "hold", "1")));

        assertEquals(1, projection.skipped());
        assertEquals(List.of(EVENT_B), projection.rows().stream().filter(r -> r.type().equals("candidate"))
                .map(Row::externalId).toList(), "the readable event and its relation stay");
    }

    @Test
    void anEventWithoutAReadableIdMakesUnknownEventRelationsUnsafeToShow() {
        Projection projection = ReviewTargetReader.read(s2("{\"eventCandidateId\":\"bad\"}"),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", "evc-unseen"), "hold", "1"),
                        relation(rel('2'), "SUPPLIES", endpoint("company", "A"), endpoint("company", "B"), "hold", "1")));

        assertEquals(1, projection.skipped());
        assertEquals(1, projection.unknownEvents());
        assertEquals(List.of(rel('2'), rel('2')), projection.rows().stream().map(Row::externalId).toList(),
                "a relation without events is unaffected");
    }

    @Test
    void twoEventsUnderOneIdAreNeitherListed() {
        Projection projection = ReviewTargetReader.read(
                s2(event(EVENT_A, "candidate", "x"), event(EVENT_A, "candidate", "x")),
                s3(relation(rel('1'), "PARTICIPATES_IN", endpoint("company", "A"), endpoint("event", EVENT_A), "hold", "1")));

        assertEquals(List.of(), projection.rows());
        assertEquals(1, projection.skipped());
    }

    @Test
    void anEventToEventRelationNeedsEveryEventEndpointListed() {
        Map<String, Row> rows = byKey(ReviewTargetReader.read(
                s2(event(EVENT_A, "candidate", "x"), event(EVENT_B, "candidate", "x"), event(EVENT_HELD, "candidate", "held")),
                s3(relation(rel('1'), "FOLLOWS", endpoint("event", EVENT_A), endpoint("event", EVENT_HELD), "hold", "1"),
                        relation(rel('2'), "FOLLOWS", endpoint("event", EVENT_HELD), endpoint("event", EVENT_A), "hold", "1"),
                        relation(rel('3'), "FOLLOWS", endpoint("event", EVENT_B), endpoint("event", EVENT_A), "hold", "1"))));

        assertEquals(java.util.Set.of("candidate:" + EVENT_B, "relation:" + rel('3')), rows.keySet(),
                "a held endpoint on either side keeps the relation out; otherwise the first event owns it");
    }

    @Test
    void sourceIdsInAnyLanguageAndTypesWithDigitsAreRead() {
        Map<String, Row> rows = byKey(ReviewTargetReader.read(s2(),
                s3(relation(rel('1'), "SUPPLIES_V2", endpoint("company", "삼성전자"), endpoint("company", "B"), "hold", "1"))));

        assertEquals(List.of("B", "삼성전자"), rows.get("candidate:" + rel('1')).companyIds());
        assertEquals(List.of("SUPPLIES_V2"), rows.get("relation:" + rel('1')).relationTypes());
    }
    private static String bound(String incoming, String observation) {
        return """
                {"binding":{"incoming":"%s","documents":{"member":{"observation":{"documentId":"member-doc","rawVersion":"%s",
                 "documentVersion":"%s"}},"doc-key":{"observation":%s}}},"eventCandidates":[]}"""
                .formatted(incoming, "7".repeat(64), "8".repeat(64), observation);
    }

    @Test
    void theAnalysedDocumentIsTheIncomingOneOfTheBindingAndNothingElse() {
        String observation = """
                {"roundId":"r","sourceId":"s","page":0,"ordinal":1,"documentId":"문서-1","rawVersion":"%s","documentVersion":"%s"}"""
                .formatted("5".repeat(64), "6".repeat(64));
        assertEquals(new ReviewTargetReader.Document("문서-1", "5".repeat(64), "6".repeat(64)),
                ReviewTargetReader.read(bound("doc-key", observation), s3()).document(), "the incoming document, not a member");
        assertEquals("member-doc", ReviewTargetReader.read(bound("member", observation), s3()).document().documentId());

        assertNull(ReviewTargetReader.read(s2(), s3()).document(), "no binding");
        assertNull(ReviewTargetReader.read(bound("missing", observation), s3()).document(), "an incoming key with no document");
        assertNull(ReviewTargetReader.read(bound("doc-key", observation.replace("5".repeat(64), "5".repeat(63))), s3())
                .document(), "a raw version that is no exact hash");
        assertNull(ReviewTargetReader.read(bound("doc-key", observation.replace("\"문서-1\"", "\"\"")), s3()).document(),
                "an empty document id");
    }
}
