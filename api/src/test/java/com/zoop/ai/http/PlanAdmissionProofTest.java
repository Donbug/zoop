package com.zoop.ai.http;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;

import com.zoop.ai.plan.PlanIdentity;
import com.zoop.ai.plan.PlanReference;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Executes the real proof CLI against a loopback service, with a valid preceding status and conflicting result status. */
class PlanAdmissionProofTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String S2 = PipelineJson.UPSTREAM_JOB;
    private static final PlanReference REFERENCE = new PlanReference("s2plan-" + "5".repeat(64), "6".repeat(64));
    private static final String S3 = PlanIdentity.relationJobId(REFERENCE, S2, PipelineJson.INPUT);
    @TempDir
    Path temporary;

    static Stream<Arguments> conflictingResults() {
        return Stream.of(
                Arguments.of("s2", "approval"), Arguments.of("s2", "input"), Arguments.of("s2", "source"),
                Arguments.of("s2", "mode"), Arguments.of("s2", "providerCalls"), Arguments.of("s2", "paidModelCalls"),
                Arguments.of("s2", "startedWithoutReceipt"),
                Arguments.of("s3", "upstream"), Arguments.of("s3", "input"), Arguments.of("s3", "source"),
                Arguments.of("s3", "mode"), Arguments.of("s3", "providerCalls"), Arguments.of("s3", "modelCalls"),
                Arguments.of("s3", "startedWithoutReceipt"));
    }

    @ParameterizedTest(name = "{0} result contradicts preceding status: {1}")
    @MethodSource("conflictingResults")
    void inconsistentConsumedResultCannotPublishSuccessEvidence(String stage, String conflict) throws Exception {
        try (var server = new StubAiServer()) {
            server.respond(seen -> response(seen, stage, conflict));
            Path evidence = temporary.resolve("evidence");
            int exit = invoke(server, evidence);
            assertEquals(1, exit, "the actual proof CLI must refuse the result, not report zero calls from the prior status");
            assertTrue(Files.isRegularFile(evidence.resolve("reference.json")));
            assertTrue(Files.isRegularFile(evidence.resolve("unit-identities.json")));
            assertFalse(Files.exists(evidence.resolve("result.json")));
            String resultPath = "/internal/v1/" + (stage.equals("s2") ? "extraction-jobs/" + S2 : "relation-jobs/" + S3) + "/result";
            assertTrue(server.requests.stream().anyMatch(seen -> seen.path().equals(resultPath)), "must reach the conflicting result seam");
            if (stage.equals("s2")) {
                assertFalse(server.requests.stream().anyMatch(seen -> seen.path().startsWith("/internal/v1/relation-jobs")),
                        "a refused S2 result must not reach S3");
            }
        }
    }

    @Test
    void validConsumedResultsProduceActualCliEvidence() throws Exception {
        try (var server = new StubAiServer()) {
            server.respond(seen -> response(seen, "none", "none"));
            Path evidence = temporary.resolve("evidence");
            assertEquals(0, invoke(server, evidence));
            var result = JSON.readTree(Files.readAllBytes(evidence.resolve("result.json")));
            assertEquals(0, result.get("providerCalls").longValue());
            assertEquals(S3, result.get("units").get(0).get("relationJobId").stringValue());
            assertEquals(1, result.get("units").get(0).get("s2EventCandidates").intValue());
            assertEquals(1, result.get("units").get(0).get("s3Candidates").intValue());
        }
    }

    private int invoke(StubAiServer server, Path evidence) throws Exception {
        Path config = temporary.resolve("config.json");
        Path reference = temporary.resolve("reference.json");
        Files.write(config, JSON.writeValueAsBytes(Map.of("baseUrl", server.baseUrl(), "token", StubAiServer.TOKEN)));
        Files.write(reference, JSON.writeValueAsBytes(Map.of("schemaVersion", PlanReference.SCHEMA_VERSION,
                "planId", REFERENCE.planId(), "planDigest", REFERENCE.planDigest())));
        String classpath = System.getProperty("zoop.ai.proof.classpath");
        assertNotNull(classpath, "Gradle test must provide the actual test runtime classpath");
        Process child = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-cp", classpath,
                "com.zoop.ai.PlanAdmissionProof", config.toString(), reference.toString(), evidence.toString())
                .redirectOutput(temporary.resolve("stdout.txt").toFile()).redirectError(temporary.resolve("stderr.txt").toFile()).start();
        try {
            assertTrue(child.waitFor(Duration.ofSeconds(15).toMillis(), TimeUnit.MILLISECONDS), "bounded actual CLI execution");
            return child.exitValue();
        } finally {
            if (child.isAlive()) {
                child.destroyForcibly();
                child.waitFor();
            }
        }
    }

    private static StubAiServer.Reply response(StubAiServer.Seen seen, String stage, String conflict) {
        String path = seen.path();
        if (path.startsWith("/internal/v1/plan-admissions")) {
            return StubAiServer.Reply.json(seen.method().equals("POST") ? 201 : 200, admission());
        }
        if (path.equals("/internal/v1/extraction-jobs") || path.equals("/internal/v1/extraction-jobs/" + S2)) {
            return StubAiServer.Reply.json(200, ready(PipelineJson.extractionStatus(S2, "ready", "fetch_result", PipelineJson.APPROVED, null)));
        }
        if (path.equals("/internal/v1/extraction-jobs/" + S2 + "/result")) {
            String job = PipelineJson.extractionJob(S2, PipelineJson.INPUT).replace("\"title\":", "\"approved\":false,\"title\":");
            String result = ready(PipelineJson.extractionResult(S2, PipelineJson.APPROVED, null, null, job));
            return StubAiServer.Reply.json(200, stage.equals("s2") ? conflict(result, stage, conflict) : result);
        }
        if (path.equals("/internal/v1/relation-jobs") || path.equals("/internal/v1/relation-jobs/" + S3)) {
            return StubAiServer.Reply.json(200, ready(PipelineJson.relationStatus(S3, "ready", "fetch_result", PipelineJson.INPUT, null)));
        }
        if (path.equals("/internal/v1/relation-jobs/" + S3 + "/result")) {
            String job = PipelineJson.relationJob(S3, PipelineJson.INPUT, PipelineJson.INPUT, "0");
            String result = ready(PipelineJson.relationResult(S3, null, job)).replace(PipelineJson.UPSTREAM_DIGEST, PipelineJson.INPUT);
            return StubAiServer.Reply.json(200, stage.equals("s3") ? conflict(result, stage, conflict) : result);
        }
        return StubAiServer.Reply.json(500, "{}");
    }

    private static String ready(String document) {
        return document.replace("\"state\":\"pending\",\"dispatchCount\"", "\"state\":\"idle\",\"dispatchCount\"");
    }

    private static String conflict(String document, String stage, String conflict) {
        return switch (conflict) {
            case "approval" -> document.replace(PipelineJson.APPROVED, PipelineJson.OTHER);
            case "input" -> {
                String changed = document.replace(PipelineJson.INPUT, PipelineJson.OTHER);
                if (stage.equals("s3")) {
                    // Keep the manifest upstream exact: only the S3 result's own status/payload/sourceVersion move together.
                    changed = changed.replace("\"upstream\":{\"jobId\":\"" + S2 + "\",\"inputDigest\":\"" + PipelineJson.OTHER + "\"}",
                            "\"upstream\":{\"jobId\":\"" + S2 + "\",\"inputDigest\":\"" + PipelineJson.INPUT + "\"}");
                }
                yield changed;
            }
            case "upstream" -> document.replace("\"jobId\":\"" + S2 + "\"", "\"jobId\":\"other-s2\"");
            case "source" -> document.replace("\"sourceKind\":\"synthetic\"", "\"sourceKind\":\"actual\"");
            case "mode" -> document.replace("\"executionMode\":\"replay\",\"recordingKind\":\"authored-test\"",
                    "\"executionMode\":\"live\",\"recordingKind\":\"provider\"");
            default -> document.replace("\"" + conflict + "\":0", "\"" + conflict + "\":1");
        };
    }

    private static String admission() {
        var provenance = Map.of("sourceKind", "synthetic", "executionMode", "replay", "recordingKind", "authored-test");
        var manifest = new java.util.LinkedHashMap<String, Object>();
        manifest.put("schemaVersion", "zoop-ai-plan-manifest-1");
        manifest.put("planId", REFERENCE.planId());
        manifest.put("planDigest", REFERENCE.planDigest());
        manifest.put("receiptSha256", PipelineJson.OTHER);
        manifest.put("principal", "alpha");
        manifest.put("round", Map.of("sourceId", "source", "roundId", "round", "ingestionInputDigest", PipelineJson.INPUT));
        manifest.put("provenance", provenance);
        manifest.put("units", java.util.List.of(Map.of("unitKey", S2, "extractionInputDigest", PipelineJson.INPUT,
                "extractionSubmit", Map.of("schemaVersion", "zoop-extraction-s2-2", "jobId", S2, "approvedRequestDigest", PipelineJson.APPROVED),
                "relationSubmit", Map.of("schemaVersion", "zoop-relation-s3", "jobId", S3, "provenance", provenance,
                        "upstream", Map.of("jobId", S2, "inputDigest", PipelineJson.INPUT)))));
        String publicManifest = JSON.writeValueAsString(manifest);
        manifest.put("manifestDigest", PlanIdentity.sha256(PlanAdmissionWire.canonical(WireJson.parse(publicManifest, "manifest"), false)));
        return JSON.writeValueAsString(Map.of("schemaVersion", PlanReference.SCHEMA_VERSION,
                "admissionId", PlanIdentity.admissionId("alpha", REFERENCE), "acceptedAt", PipelineJson.STAMP,
                "policyRevision", 1, "policyDigest", PipelineJson.OTHER, "manifest", manifest,
                "authority", java.util.Collections.singletonMap("unused", "unused")))
                .replace("\"authority\":{\"unused\":\"unused\"}", "\"authority\":{\"state\":\"active\",\"reason\":null}");
    }
}
