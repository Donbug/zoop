package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;

class S3ImpactRowsTest {
    static ObjectNode bundle() throws Exception {
        try (var in = S3ImpactRowsTest.class.getResourceAsStream("/graph-handoff/export-impacts.json")) {
            return (ObjectNode) StrictJson.parseObject(in.readAllBytes()).object("bundle").node().deepCopy();
        }
    }
    static List<Relation> visible(ObjectNode b) {
        return Obj.of(b).objects("relations").stream().filter(r -> "INVOLVES".equals(r.string("type")))
                .map(r -> new Relation(r.string("id"), r.string("type"), r.string("source"), r.string("target"), null, null,
                        r.strings("evidenceIds"), List.of())).toList();
    }
    static ObjectNode verified(ObjectNode b) {
        for (var row : b.path("impacts")) if ("verified".equals(row.path("status").asString())) return (ObjectNode) row;
        throw new AssertionError();
    }
    @Test void readsTheTeamProducerFixtureWithoutAggregatingConflictingSourceRowsOrPublishingProposal() throws Exception {
        var b = bundle(); var rows = S3ImpactRows.read(Obj.of(b), visible(b));
        assertEquals(6, rows.size());
        assertEquals(List.of("positive", "negative", "undetermined"), rows.stream().filter(r -> r.label() != null).map(S3ImpactRows.Row::label).toList());
        assertTrue(rows.stream().allMatch(r -> r.provenance().executionMode().equals("replay")));
        assertEquals(2, rows.stream().map(S3ImpactRows.Row::relationId).distinct().count());
    }
    @Test void aLegacyReceiptMeansAbsentNotUndeterminedAndUnknownFutureSchemasFailClosed() throws Exception {
        var b = bundle(); b.put("schemaVersion", "zoop-graph-handoff-bundle-5"); b.remove("impacts");
        assertTrue(S3ImpactRows.read(Obj.of(b), visible(b)).isEmpty());
        b.put("schemaVersion", "zoop-graph-handoff-bundle-8");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
    }
    @Test void rejectsAStoredLabelThatDiffersFromTheVerifierEffects() throws Exception {
        var b = bundle(); verified(b).put("label", "negative");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
    }
    @Test void insufficientTargetIsUndeterminedEvenWithPositiveQuotes() throws Exception {
        var b = bundle(); verified(b).put("targetVerdict", "insufficient").put("label", "undetermined");
        assertEquals("undetermined", S3ImpactRows.read(Obj.of(b), visible(b)).stream().filter(r -> r.label() != null).findFirst().orElseThrow().label());
    }
    @Test void rejectsForeignIssueCompanyOrSourceBindings() throws Exception {
        for (String field : List.of("issueId", "companyId")) {
            var b = bundle(); verified(b).put(field, "foreign");
            assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
        }
        var b = bundle(); ((ObjectNode) verified(b).path("sourceRelation")).put("jobId", "foreign");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
    }
    @Test void rejectsMissingDuplicateAndCrossSideEvidence() throws Exception {
        var b = bundle(); var row = verified(b); var effects = (ObjectNode) row.path("effects");
        effects.withArray("negative").add(effects.path("positive").get(0).asString());
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
        var empty = bundle(); empty.withArray("impacts").remove(0);
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(empty), visible(empty)));
        var duplicate = bundle(); duplicate.withArray("impacts").add(duplicate.path("impacts").get(0).deepCopy());
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(duplicate), visible(duplicate)));
    }
    @Test void rejectsEffectsOutsideTheRelationsOwnArticleVersion() throws Exception {
        var b = bundle(); var id = verified(b).path("effects").path("positive").get(0).asString();
        for (var e : b.path("evidence")) if (id.equals(e.path("id").asString())) ((ObjectNode) e).put("articleVersion", "foreign");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
    }
    @Test void nonVerifiedRowsCannotCarryALabelAndSyntheticReplayCannotClaimLiveProviderProvenance() throws Exception {
        var b = bundle(); ((ObjectNode) b.path("impacts").get(0)).put("label", "positive");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
        var p = bundle(); ((ObjectNode) p.path("sources").get(0).path("provenance")).put("executionMode", "live");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(p), visible(p)));
    }
}
