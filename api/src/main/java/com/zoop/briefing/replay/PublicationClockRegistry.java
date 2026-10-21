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
                Instant timestamp = awareTimestamp(row.string("publishedAt"));
                awareTimestamp(row.string("checkedAt"));
                if (row.count("httpStatus") != 200 || row.string("finalUrl").isBlank()) bad();
                String hash = row.string("htmlSha256"); if (!hash.matches("[0-9a-f]{64}")) bad();
                Path raw = path.getParent().resolve("html").resolve(hash + ".html");
                if (!Files.isRegularFile(raw, LinkOption.NOFOLLOW_LINKS) || Files.size(raw) > 4_000_000) bad();
                byte[] htmlBytes = Files.readAllBytes(raw);
                if (!hash.equals(Canonical.sha256(htmlBytes))) bad();
                boolean declared = false;
                for (StrictJson.Obj declaration : row.objects("declarations")) {
                    try { if (sameObservedTimestamp(awareTimestamp(declaration.string("value")), timestamp)) declared = true; }
                    catch (java.time.DateTimeException ignored) { /* Date-only declarations are not timestamps. */ }
                }
                if (!declared) throw new IllegalArgumentException("Publisher declaration does not match recorded timestamp: " + id + " / " + timestamp);
                if (source.has("originalPublicationVerified") && source.path("originalPublicationVerified").asBoolean()
                        && source.has("publishedAt") && !source.path("publishedAt").isNull()
                        && !sameObservedTimestamp(awareTimestamp(source.path("publishedAt").stringValue()), timestamp)) bad();
                verified.put(key, new Clock(id, body, timestamp, Canonical.digest(row.node()), hash, row.node()));
                html.putIfAbsent(hash, htmlBytes);
            }
        } catch (java.io.IOException unavailable) {
            throw new IllegalArgumentException("Publication clock evidence is unavailable", unavailable);
        }
    }

    /** Accept only explicit ISO offsets; compact offsets and ASCII spacing change notation, never the timezone. */
    private static Instant awareTimestamp(String original) {
        if (!original.matches("\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}(?::\\d{2}(?:\\.\\d{1,9})?)? ?(?:Z|[+-]\\d{2}:?\\d{2})")) {
            throw new java.time.DateTimeException("Publisher declaration is not an explicitly zoned ISO timestamp");
        }
        String normalized = original.charAt(10) == ' ' ? original.substring(0, 10) + "T" + original.substring(11) : original;
        normalized = normalized.replaceFirst(" ([+-]\\d{2}:?\\d{2}|Z)$", "$1")
                .replaceFirst("([+-]\\d{2})(\\d{2})$", "$1:$2");
        return OffsetDateTime.parse(normalized).toInstant();
    }

    /** The Python observer stores microseconds; retain raw nanoseconds and refuse any resulting window change. */
    private static boolean sameObservedTimestamp(Instant declaration, Instant recorded) {
        if (declaration.equals(recorded)) return true;
        Instant microsecond = declaration.truncatedTo(java.time.temporal.ChronoUnit.MICROS);
        if (!microsecond.equals(recorded.truncatedTo(java.time.temporal.ChronoUnit.MICROS))) return false;
        var local = microsecond.atOffset(java.time.ZoneOffset.ofHours(9)).toLocalTime();
        boolean cutoff = local.equals(java.time.LocalTime.of(9, 20)) || local.equals(java.time.LocalTime.of(17, 30));
        if (cutoff && declaration.equals(microsecond) != recorded.equals(microsecond)) {
            throw new IllegalArgumentException("Publisher precision truncation changes the briefing window");
        }
        return true;
    }

    private static void bad() { throw new IllegalArgumentException("Publication clock registry/source/HTML identity is invalid"); }
}
