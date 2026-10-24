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
    private final ExclusionRequestParser parser = new ExclusionRequestParser();

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
                // A relation retraction never withdraws article text or quotes (consumption rule 5).
                r -> {
                    r.put("cause", "relation-retraction");
                    ObjectNode changed = r.putObject("changed");
                    changed.put("kind", "s3-relation");
                    changed.put("jobId", "s3-job");
                    changed.put("relationCandidateId", "rc-" + "5".repeat(64));
                },
                r -> r.put("cause", "relation-retraction"));
        for (Consumer<ObjectNode> forgery : forgeries) {
            ObjectNode report = ExposureReports.report(ExposureReports.handoff("handoff-1", List.of("issue-a"), List.of(), true));
            forgery.accept(report);
            ExclusionException refused = assertThrows(ExclusionException.class,
                    () -> parser.parse(ExposureReports.exclude(report)));
            assertEquals(ExclusionFailure.REPORT_INVALID, refused.failure());
        }
    }

    @Test
    void aLiftNamesOneVersionAndItsTargetsAndAnythingElseIsAnInvalidRequest() {
        Lift lift = assertInstanceOf(Lift.class, parser.parse(ExposureReports.lift("gv-test", "issue-a", "issue-b")));
        assertEquals("gv-test", lift.graphVersionId());
        assertEquals(2, lift.targets().size());
        assertEquals("정정 확인 후 해제", lift.reason());

        for (byte[] invalid : List.of(ExposureReports.lift("gv-test"), ExposureReports.lift("gv-test", "issue-a", "issue-a"),
                ExposureReports.utf8("{\"schemaVersion\":\"zoop-disclosure-exclusion-1\",\"action\":\"delete\","
                        + "\"operator\":\"a\",\"reason\":\"r\"}"),
                ExposureReports.utf8("not json"))) {
            assertEquals(ExclusionFailure.REQUEST_INVALID,
                    assertThrows(ExclusionException.class, () -> parser.parse(invalid)).failure());
        }
        ObjectNode blankReason = (ObjectNode) StrictJson.parseObject(ExposureReports.lift("gv-test", "issue-a")).node();
        blankReason.put("reason", "   ");
        assertEquals(ExclusionFailure.REQUEST_INVALID,
                assertThrows(ExclusionException.class, () -> parser.parse(StrictJson.write(blankReason))).failure());
    }
}
