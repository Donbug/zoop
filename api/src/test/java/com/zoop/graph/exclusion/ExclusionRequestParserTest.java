package com.zoop.graph.exclusion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.List;
import java.util.function.Consumer;

import com.zoop.common.json.StrictJson;
import com.zoop.graph.exclusion.ExclusionRequest.Exclude;
import com.zoop.graph.exclusion.ExclusionRequest.Lift;
import com.zoop.graph.exclusion.ExclusionRequest.Target;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;

class ExclusionRequestParserTest {
    @Test
    void aQueryNamesTheChangeAndTheVersionsAndIsRefusedWhenEitherIsOutsideTheContract() {
        var query = (ExclusionRequest.Query) new ExclusionRequestParser().parse(
                ExposureReports.query("q-1", ExposureReports.sourceChange(), "gv-a", "gv-b"));
        assertEquals("source-change", query.cause());
        assertEquals(java.util.List.of("gv-a", "gv-b"), query.graphVersionIds());
        assertEquals("synthetic-source", query.changed().get("sourceId").stringValue());

        var relation = tools.jackson.databind.node.JsonNodeFactory.instance.objectNode();
        relation.put("kind", "s3-relation");
        relation.put("jobId", "s3-job");
        relation.put("relationCandidateId", "rc-" + "a".repeat(64));
        assertEquals("relation-retraction",
                ((ExclusionRequest.Query) new ExclusionRequestParser().parse(ExposureReports.query("q-2", relation))).cause());

        var unknown = ExposureReports.sourceChange();
        unknown.put("extra", 1);
        for (byte[] invalid : java.util.List.of(ExposureReports.query("q-3", unknown),
                ExposureReports.query("q-4", ExposureReports.sourceChange(), "gv-a", "gv-a"),
                ExposureReports.query("q-5", ExposureReports.sourceChange(),
                        java.util.stream.IntStream.rangeClosed(1, 21).mapToObj(i -> "gv-" + i).toArray(String[]::new)))) {
            var failure = org.junit.jupiter.api.Assertions.assertThrows(ExclusionException.class,
                    () -> new ExclusionRequestParser().parse(invalid));
            assertEquals(ExclusionFailure.REQUEST_INVALID, failure.failure());
        }
    }

    private final ExclusionRequestParser parser = new ExclusionRequestParser();

    @Test
    void publicationExclusionPinsTheReceiptAndHashesEveryExplicitTarget() {
        ObjectNode request = StrictJson.newObject();
        request.put("schemaVersion", ExclusionRequestParser.SCHEMA_VERSION); request.put("action", "exclude-publication");
        request.put("requestId", "publication-exclusion-1"); request.put("operator", "operator"); request.put("reason", "withdraw selected claim");
        request.put("graphVersionId", "gv-" + "a".repeat(64)); request.put("receiptSha256", "b".repeat(64));
        request.putArray("targets").addObject().put("kind", "issue").put("id", "issue-a");
        var first = assertInstanceOf(ExclusionRequest.PublicationExclude.class, parser.parse(StrictJson.write(request)));
        assertEquals(List.of(new Target("issue", "issue-a", "")), first.targets());
        request.put("receiptSha256", "c".repeat(64));
        assertNotEquals(first.requestSha256(), parser.parse(StrictJson.write(request)).requestSha256());
        request.put("humanAllow", true);
        assertEquals(ExclusionFailure.REQUEST_INVALID,
                assertThrows(ExclusionException.class, () -> parser.parse(StrictJson.write(request))).failure());
    }

    @Test
    void anExcludeCarriesTheReportsHandoffsPinsAndEveryProposedTarget() {
        ObjectNode report = ExposureReports.report(ExposureReports.handoff("handoff-1", List.of("issue-a"), List.of("edge-a"), true),
                ExposureReports.handoff("handoff-2", List.of(), List.of(), false));

        Exclude exclude = assertInstanceOf(Exclude.class, parser.parse(ExposureReports.exclude(report)));

        assertEquals("source-change", exclude.report().cause());
        assertEquals(64, exclude.report().sha256().length());
        var first = exclude.report().handoffs().get(0);
        assertEquals(List.of(ExposureReports.DIGEST_M, ExposureReports.DIGEST_B, ExposureReports.DIGEST_C),
                List.of(first.manifestDigest(), first.bundleDigest(), first.contentDigest()));
        assertEquals(List.of(new Target("article", ExposureReports.ARTICLE, ExposureReports.ARTICLE_VERSION),
                new Target("issue", "issue-a", ""), new Target("relation", "edge-a", ""),
                new Target("evidence", ExposureReports.EVIDENCE, "")), first.targets());
        assertEquals(List.of(), exclude.report().handoffs().get(1).targets(), "an unexposed handoff proposes nothing");
    }

    @Test
    void theReportDigestIsOfItsContentNotOfTheRequestAroundIt() {
        ObjectNode one = ExposureReports.report(ExposureReports.handoff("handoff-1", List.of("issue-a"), List.of(), false));
        ObjectNode other = ExposureReports.report(ExposureReports.handoff("handoff-1", List.of("issue-b"), List.of(), false));
        String digest = ((Exclude) parser.parse(ExposureReports.exclude(one))).report().sha256();
        assertNotEquals(digest, ((Exclude) parser.parse(ExposureReports.exclude(other))).report().sha256());
        assertEquals(digest, ((Exclude) parser.parse(ExposureReports.exclude(one.deepCopy()))).report().sha256());
    }

    @Test
    void aReportThatIsNotExactlyTheProducersShapeIsRefusedWhole() {
        List<Consumer<ObjectNode>> forgeries = List.of(
                r -> r.put("schemaVersion", "zoop-handoff-exposure-2"),
                r -> r.put("extra", 1),
                r -> ((ObjectNode) r.get("usage")).put("modelCalls", 1),
                r -> ((ObjectNode) r.get("scope")).putArray("handoffIds").add("another"),
                r -> ((ObjectNode) r.get("handoffs").get(0)).put("bundleSchema", "zoop-graph-handoff-bundle-6"),
                r -> ((ObjectNode) r.get("handoffs").get(0).get("counts")).put("issues", 9),
                r -> ((ObjectNode) r.get("handoffs").get(0)).put("exposed", false),
                r -> ((ObjectNode) r.get("handoffs").get(0)).put("manifestDigest", "A".repeat(64)),
                // Types, nullability, enums, consts and caps of the closed schema, not only its keys.
                r -> ((ObjectNode) r.get("changed")).putNull("sourceId"),
                r -> ((ObjectNode) r.get("changed")).put("sourceId", ""),
                r -> ((ObjectNode) r.get("identity")).put("recordedInIngestion", "yes"),
                r -> ((ObjectNode) r.get("handoffs").get(0).get("articles").get(0)).put("documentVersion", "v1"),
                r -> ((ObjectNode) r.get("handoffs").get(0).get("articles").get(0)).put("documentId", 7),
                r -> ((ObjectNode) r.get("handoffs").get(0).get("issues").get(0)).putArray("reasons").add("made-up"),
                r -> r.put("consistency", "no locks"),
                r -> r.put("effect", "excluded everything"),
                r -> {
                    ObjectNode changed = r.putObject("changed");
                    changed.put("kind", "document");
                    changed.put("documentId", "doc");
                    changed.put("documentVersion", "x");
                    changed.putNull("rawVersion");
                },
                r -> {
                    ObjectNode changed = r.putObject("changed");
                    changed.put("kind", "grant");
                    changed.put("grantId", "grant");
                    changed.put("revision", 3);
                },
                r -> {
                    var issues = ((ObjectNode) r.get("handoffs").get(0)).putArray("issues");
                    for (int i = 0; i < 2001; i++) {
                        ObjectNode issue = issues.addObject();
                        issue.put("id", "issue-" + i);
                        issue.putArray("reasons").add("source-document");
                    }
                    ((ObjectNode) r.get("handoffs").get(0).get("counts")).put("issues", 2001);
                },
                // A relation retraction never withdraws article text or quotes (consumption rule 5).
                r -> {
                    r.put("cause", "relation-retraction");
                    ObjectNode changed = r.putObject("changed");
                    changed.put("kind", "s3-relation");
                    changed.put("jobId", "s3-job");
                    changed.put("relationCandidateId", "rc-" + "5".repeat(64));
                },
                r -> r.put("cause", "relation-retraction"),
                r -> {
                    // A relation retraction with a relation candidate id that is not rc-<64 hex>.
                    r.put("cause", "relation-retraction");
                    ObjectNode changed = r.putObject("changed");
                    changed.put("kind", "s3-relation");
                    changed.put("jobId", "s3-job");
                    changed.put("relationCandidateId", "candidate");
                });
        for (Consumer<ObjectNode> forgery : forgeries) {
            ObjectNode report = ExposureReports.report(ExposureReports.handoff("handoff-1", List.of("issue-a"), List.of(), true));
            forgery.accept(report);
            ExclusionException refused = assertThrows(ExclusionException.class,
                    () -> parser.parse(ExposureReports.exclude(report)));
            assertEquals(ExclusionFailure.REPORT_INVALID, refused.failure());
        }
    }

    @Test
    void nullableFieldsOfTheSchemaMayBeNull() {
        ObjectNode report = ExposureReports.report(ExposureReports.handoff("handoff-1", List.of("issue-a"), List.of(), true));
        ((ObjectNode) report.get("identity")).putNull("recordedInIngestion");
        ObjectNode changed = report.putObject("changed");
        changed.put("kind", "grant");
        changed.put("grantId", "grant-1");
        changed.putNull("revision");
        assertInstanceOf(Exclude.class, parser.parse(ExposureReports.exclude(report)));
    }

    @Test
    void theRequestIdNamesTheCommandAndTheHashCoversTheWholeRequest() {
        ObjectNode report = ExposureReports.report(ExposureReports.handoff("handoff-1", List.of("issue-a"), List.of(), false));
        Exclude one = (Exclude) parser.parse(ExposureReports.exclude("cmd-1", report));
        assertEquals("cmd-1", one.requestId());
        assertEquals(one.requestSha256(), parser.parse(ExposureReports.exclude("cmd-1", report.deepCopy())).requestSha256());
        ObjectNode otherReason = (ObjectNode) StrictJson.parseObject(ExposureReports.exclude("cmd-1", report)).node();
        otherReason.put("reason", "다른 사유");
        assertNotEquals(one.requestSha256(), parser.parse(StrictJson.write(otherReason)).requestSha256());

        for (String field : List.of("requestId", "expectedRevision")) {
            ObjectNode lift = (ObjectNode) StrictJson.parseObject(ExposureReports.lift("gv-test", 0, "issue-a")).node();
            lift.remove(field);
            assertEquals(ExclusionFailure.REQUEST_INVALID,
                    assertThrows(ExclusionException.class, () -> parser.parse(StrictJson.write(lift))).failure());
        }
        ObjectNode negative = (ObjectNode) StrictJson.parseObject(ExposureReports.lift("gv-test", 0, "issue-a")).node();
        negative.put("expectedRevision", -1);
        assertEquals(ExclusionFailure.REQUEST_INVALID,
                assertThrows(ExclusionException.class, () -> parser.parse(StrictJson.write(negative))).failure());
    }

    @Test
    void aLiftNamesOneVersionAndItsTargetsAndAnythingElseIsAnInvalidRequest() {
        Lift lift = assertInstanceOf(Lift.class, parser.parse(ExposureReports.lift("gv-test", 4, "issue-a", "issue-b")));
        assertEquals("gv-test", lift.graphVersionId());
        assertEquals(4, lift.expectedRevision());
        assertEquals(2, lift.targets().size());
        assertEquals("정정 확인 후 해제", lift.reason());

        for (byte[] invalid : List.of(ExposureReports.lift("gv-test", 0), ExposureReports.lift("gv-test", 0, "issue-a", "issue-a"),
                ExposureReports.utf8("{\"schemaVersion\":\"zoop-disclosure-exclusion-1\",\"requestId\":\"cmd\","
                        + "\"action\":\"delete\",\"operator\":\"a\",\"reason\":\"r\"}"),
                ExposureReports.utf8("not json"))) {
            assertEquals(ExclusionFailure.REQUEST_INVALID,
                    assertThrows(ExclusionException.class, () -> parser.parse(invalid)).failure());
        }
        ObjectNode blankReason = (ObjectNode) StrictJson.parseObject(ExposureReports.lift("gv-test", 0, "issue-a")).node();
        blankReason.put("reason", "   ");
        assertEquals(ExclusionFailure.REQUEST_INVALID,
                assertThrows(ExclusionException.class, () -> parser.parse(StrictJson.write(blankReason))).failure());
    }
}
