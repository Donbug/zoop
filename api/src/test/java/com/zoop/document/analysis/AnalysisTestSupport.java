package com.zoop.document.analysis;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;

import com.zoop.common.json.Canonical;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static com.zoop.document.analysis.AnalysisWorld.JSON;

/** The world of one test, plus the fixture editing helpers the analysis tests share. */
abstract class AnalysisTestSupport {
    static final String JOB_HEX = "01".repeat(16);
    static final String ANALYSIS_HEX = "a1".repeat(16);

    @TempDir
    Path temp;
    AnalysisWorld world;

    @BeforeEach
    void openWorld() throws IOException {
        world = new AnalysisWorld(temp);
    }

    @AfterEach
    void closeWorld() {
        world.close();
    }

    /** Prepares one analysis with the fixture's first job id ({@code s1-0101...}) and returns its id. */
    String prepareAnalysis(String kind) {
        return prepareAnalysis(kind, "01", null);
    }

    /**
     * Prepares one analysis whose job id is the one a worker fixture scenario was run under ({@code jobByte} repeated: the
     * summary is {@code 01}, its cache-served twin {@code 02}, the sentiment {@code 03}, the held summary {@code 04}, the
     * rejected one {@code 05} and the failed one {@code 06}) and returns the new analysis id.
     */
    String prepareAnalysis(String kind, String jobByte, String expectedLatest) {
        world.issue(jobByte.repeat(16), ("a" + jobByte.charAt(1)).repeat(16));
        return AnalysisWorld.prepared(world.prepare(kind, expectedLatest)).analysisId();
    }

    static String jobOf(String jobByte) {
        return "s1-" + jobByte.repeat(16);
    }

    static String analysisOf(String jobByte) {
        return "da-" + ("a" + jobByte.charAt(1)).repeat(16);
    }

    /** The service knows the job and answers with this worker scenario. */
    void serve(ObjectNode scenario) {
        world.serve((ObjectNode) scenario.get("status"), (ObjectNode) scenario.get("envelope"));
    }

    static ObjectNode job(ObjectNode scenario) {
        return (ObjectNode) scenario.get("envelope").get("job");
    }

    static ObjectNode artifact(ObjectNode scenario, String kind) {
        for (JsonNode artifact : job(scenario).get("artifacts").values()) {
            if (kind.equals(artifact.get("kind").stringValue())) {
                return (ObjectNode) artifact;
            }
        }
        throw new IllegalStateException("no " + kind + " artifact in the fixture");
    }

    static ObjectNode statusOf(ObjectNode scenario) {
        return (ObjectNode) scenario.get("status");
    }

    static ObjectNode envelopeOf(ObjectNode scenario) {
        return (ObjectNode) scenario.get("envelope");
    }

    /**
     * Recomputes the result version of an artifact whose answer a test edited, as the worker defines it, so that the edit is
     * judged by the content gates instead of being caught as a digest mismatch.
     */
    static void retag(ObjectNode artifact) {
        ObjectNode version = JSON.createObjectNode();
        version.put("inputDigest", artifact.get("inputDigest").stringValue());
        version.put("kind", artifact.get("kind").stringValue());
        version.set("result", artifact.get("result"));
        artifact.put("resultVersion", "result-" + Canonical.digest(version));
    }

    static ArrayNode array(JsonNode node) {
        return (ArrayNode) node;
    }

    static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (java.security.NoSuchAlgorithmException error) {
            throw new IllegalStateException(error);
        }
    }

    static String sha256(String text) {
        return sha256(text.getBytes(StandardCharsets.UTF_8));
    }

    byte[] read(String directory, String name) throws IOException {
        return Files.readAllBytes(world.file(directory, name));
    }

    /** The text between two Unicode code point offsets, computed without any helper of the code under test. */
    static String slice(String text, int start, int end) {
        int from = text.offsetByCodePoints(0, start);
        return text.substring(from, text.offsetByCodePoints(from, end - start));
    }
}
