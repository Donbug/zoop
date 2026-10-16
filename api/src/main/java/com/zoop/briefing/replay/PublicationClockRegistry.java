package com.zoop.briefing.replay;

import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;

/** Publisher declarations observed now; this never claims that a later collected body existed unchanged then. */
final class PublicationClockRegistry {
    record Clock(String documentId, String bodySha256, Instant publishedAt, String recordSha256, String htmlSha256,
            JsonNode original) { String key() { return documentId + "\u0000" + bodySha256; } }
    final Map<String, Clock> verified = new LinkedHashMap<>();
    final Map<String, byte[]> html = new LinkedHashMap<>();
    final byte[] bytes;

    PublicationClockRegistry(Path path, String sourceSha, String expectedSha, Map<String, JsonNode> sources) {
        try {
            if (path == null || Files.size(path) > 16_000_000) bad();
            bytes = Files.readAllBytes(path);
            if (!Canonical.sha256(bytes).equals(expectedSha)) bad();
            StrictJson.Obj root = StrictJson.parseObject(bytes);
            if (!"zoop-publication-clock-registry-v1".equals(root.string("schemaVersion"))
                    || !sourceSha.equals(root.string("sourceFileSha256"))) bad();
            var seen = new java.util.HashSet<String>();
            for (StrictJson.Obj row : root.objects("records")) {
                String id = row.string("documentId"), body = row.string("bodySha256"), key = id + "\u0000" + body;
                JsonNode source = sources.get(key);
                if (source == null || !seen.add(key) || !"zoop-publication-clock-v1".equals(row.string("schemaVersion"))
                        || !sourceSha.equals(row.string("sourceFileSha256"))
                        || !source.path("url").stringValue().equals(row.string("url"))) bad();
                if (!"verified_timestamp".equals(row.string("status"))) continue;
                Instant timestamp = OffsetDateTime.parse(row.string("publishedAt")).toInstant();
                OffsetDateTime.parse(row.string("checkedAt"));
                if (row.count("httpStatus") != 200 || row.string("finalUrl").isBlank()) bad();
                String hash = row.string("htmlSha256"); if (!hash.matches("[0-9a-f]{64}")) bad();
                Path raw = path.getParent().resolve("html").resolve(hash + ".html");
                if (!Files.isRegularFile(raw, LinkOption.NOFOLLOW_LINKS) || Files.size(raw) > 4_000_000) bad();
                byte[] htmlBytes = Files.readAllBytes(raw);
                if (!hash.equals(Canonical.sha256(htmlBytes))) bad();
                boolean declared = false;
                for (StrictJson.Obj declaration : row.objects("declarations")) {
                    try { if (OffsetDateTime.parse(declaration.string("value")).toInstant().equals(timestamp)) declared = true; }
                    catch (java.time.DateTimeException ignored) { /* Date-only declarations are not timestamps. */ }
                }
                if (!declared) bad();
                if (source.has("originalPublicationVerified") && source.path("originalPublicationVerified").asBoolean()
                        && source.has("publishedAt") && !source.path("publishedAt").isNull()
                        && !OffsetDateTime.parse(source.path("publishedAt").stringValue()).toInstant().equals(timestamp)) bad();
                verified.put(key, new Clock(id, body, timestamp, Canonical.digest(row.node()), hash, row.node()));
                html.putIfAbsent(hash, htmlBytes);
            }
        } catch (java.io.IOException unavailable) {
            throw new IllegalArgumentException("Publication clock evidence is unavailable", unavailable);
        }
    }

    private static void bad() { throw new IllegalArgumentException("Publication clock registry/source/HTML identity is invalid"); }
}
