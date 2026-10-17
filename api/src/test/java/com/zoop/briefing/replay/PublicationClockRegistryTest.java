package com.zoop.briefing.replay;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

class PublicationClockRegistryTest {
    @TempDir Path directory;

    @Test
    void observedMicrosecondsMatchWithoutChangingTheHalfOpenRoundWindow() throws Exception {
        String sourceSha = "0".repeat(64), bodySha = "1".repeat(64), id = "synthetic-clock-precision";
        Path htmlDirectory = Files.createDirectory(directory.resolve("html"));
        for (String[] example : List.of(
                new String[]{"2026-10-07T14:00:42.2149486Z", "2026-10-07T14:00:42.214948Z", "accept"},
                new String[]{"2026-10-07T14:00:42.214948999Z", "2026-10-07T14:00:42.214948Z", "accept"},
                new String[]{"2026-10-02T00:20:00.0000019Z", "2026-10-02T00:20:00.000001Z", "accept"},
                new String[]{"2026-10-02T00:20:00.0000001Z", "2026-10-02T00:20:00Z", "reject"},
                new String[]{"2026-10-02T08:30:00.000000999Z", "2026-10-02T08:30:00Z", "reject"})) {
            String declaration = example[0], recorded = example[1];
            byte[] html = ("<meta property=\"article:published_time\" content=\"" + declaration + "\">").getBytes(java.nio.charset.StandardCharsets.UTF_8);
            String htmlSha = Canonical.sha256(html); Files.write(htmlDirectory.resolve(htmlSha + ".html"), html);
            var source = StrictJson.newObject().put("url", "https://example.invalid/synthetic-clock")
                    .put("originalPublicationVerified", true).put("publishedAt", declaration);
            ObjectNode record = StrictJson.newObject().put("schemaVersion", "zoop-publication-clock-v1")
                    .put("documentId", id).put("bodySha256", bodySha).put("sourceFileSha256", sourceSha)
                    .put("url", "https://example.invalid/synthetic-clock").put("finalUrl", "https://example.invalid/synthetic-clock")
                    .put("status", "verified_timestamp").put("publishedAt", recorded).put("checkedAt", "2026-10-16T01:00:00Z")
                    .put("httpStatus", 200).put("htmlSha256", htmlSha);
            record.putArray("declarations").addObject().put("source", "synthetic-jsonld:datePublished").put("value", declaration);
            ObjectNode registry = StrictJson.newObject().put("schemaVersion", "zoop-publication-clock-registry-v1").put("sourceFileSha256", sourceSha);
            registry.putArray("records").add(record);
            byte[] bytes = StrictJson.write(registry); Path path = directory.resolve("registry.json"); Files.write(path, bytes);
            if (example[2].equals("accept")) {
                var loaded = new PublicationClockRegistry(path, sourceSha, Canonical.sha256(bytes), Map.of(id + "\u0000" + bodySha, source));
                var clock = loaded.verified.get(id + "\u0000" + bodySha);
                assertEquals(Instant.parse(recorded), clock.publishedAt());
                assertEquals(declaration, clock.original().path("declarations").get(0).path("value").stringValue());
                assertEquals(Canonical.digest(record), clock.recordSha256());
                assertArrayEquals(bytes, Files.readAllBytes(path));
                assertArrayEquals(html, loaded.html.get(htmlSha));
            } else {
                var rejected = assertThrows(IllegalArgumentException.class, () -> new PublicationClockRegistry(path,
                        sourceSha, Canonical.sha256(bytes), Map.of(id + "\u0000" + bodySha, source)));
                assertTrue(rejected.getMessage().contains("changes the briefing window"));
            }
        }
    }

    @Test
    void equivalentExplicitPublisherOffsetsPreserveRawEvidenceWhileNaiveAndGuessedZonesStayRejected() throws Exception {
        String sourceSha = "0".repeat(64), bodySha = "1".repeat(64), id = "synthetic-clock-offset";
        String instant = "2026-10-02T00:20:00Z";
        var source = StrictJson.newObject().put("url", "https://example.invalid/synthetic-clock")
                .put("originalPublicationVerified", true).put("publishedAt", instant);
        Path htmlDirectory = Files.createDirectory(directory.resolve("html"));
        for (String declaration : List.of("2026-10-02T00:20:00+0000", "2026-10-01T17:20:00-0700",
                "2026-10-02 00:20:00+00:00", "2026-10-02 00:20:00 +00:00",
                "2026-10-02T00:20:00", "2026-10-02", "2026-10-02T09:20:00 KST", "2026-10-02T00:20:00+2500")) {
            byte[] html = ("<meta property=\"article:published_time\" content=\"" + declaration + "\">").getBytes(java.nio.charset.StandardCharsets.UTF_8);
            String htmlSha = Canonical.sha256(html); Files.write(htmlDirectory.resolve(htmlSha + ".html"), html);
            ObjectNode record = StrictJson.newObject().put("schemaVersion", "zoop-publication-clock-v1")
                    .put("documentId", id).put("bodySha256", bodySha).put("sourceFileSha256", sourceSha)
                    .put("url", "https://example.invalid/synthetic-clock").put("finalUrl", "https://example.invalid/synthetic-clock")
                    .put("status", "verified_timestamp").put("publishedAt", instant).put("checkedAt", "2026-10-16T01:00:00Z")
                    .put("httpStatus", 200).put("htmlSha256", htmlSha);
            record.putArray("declarations").addObject().put("source", "synthetic-meta:article:published_time").put("value", declaration);
            ObjectNode registry = StrictJson.newObject().put("schemaVersion", "zoop-publication-clock-registry-v1").put("sourceFileSha256", sourceSha);
            registry.putArray("records").add(record);
            byte[] bytes = StrictJson.write(registry); Path path = directory.resolve("registry.json"); Files.write(path, bytes);
            if (declaration.endsWith("+0000") || declaration.endsWith("-0700") || declaration.contains(" 00:20:00")) {
                var loaded = new PublicationClockRegistry(path, sourceSha, Canonical.sha256(bytes), Map.of(id + "\u0000" + bodySha, source));
                var clock = loaded.verified.get(id + "\u0000" + bodySha);
                assertEquals(Instant.parse(instant), clock.publishedAt());
                assertEquals(declaration, clock.original().path("declarations").get(0).path("value").stringValue());
                assertEquals(Canonical.digest(record), clock.recordSha256());
                assertArrayEquals(bytes, Files.readAllBytes(path));
                assertArrayEquals(html, loaded.html.get(htmlSha));
            } else {
                assertThrows(IllegalArgumentException.class, () -> new PublicationClockRegistry(path, sourceSha,
                        Canonical.sha256(bytes), Map.of(id + "\u0000" + bodySha, source)), declaration);
            }
        }
    }
}
