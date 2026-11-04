package com.zoop.briefing.server;

import com.zoop.common.json.StrictJson;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.Map;

/** Publication and first observation are different facts. A day is never converted into a publication instant. */
public record BriefingSourceClock(Instant publishedAt, LocalDate publishedDate, Instant availableAt, String basis) {
    public static BriefingSourceClock read(Map<String, Object> row) {
        var published = (Timestamp) row.get("published_at");
        if (published != null) return new BriefingSourceClock(published.toInstant(), null, published.toInstant(), "publication_instant");
        if (!"day".equals(row.get("publication_precision")) || row.get("published_date") == null || row.get("collected_at") == null)
            throw new IllegalArgumentException("source_clock_unavailable");
        LocalDate day = LocalDate.parse(row.get("published_date").toString());
        Instant observed = ((Timestamp) row.get("collected_at")).toInstant();
        if (day.isAfter(observed.atZone(ZoneId.of("Asia/Seoul")).toLocalDate()))
            throw new IllegalArgumentException("source_day_after_observation");
        return new BriefingSourceClock(null, day, observed, "first_observed");
    }

    public void put(tools.jackson.databind.node.ObjectNode node) {
        node.put("publishedAt", publishedAt == null ? null : publishedAt.toString());
        node.put("publishedDate", publishedDate == null ? null : publishedDate.toString());
        node.put("availableAt", availableAt.toString()).put("eligibilityBasis", basis);
    }

    public boolean matches(StrictJson.Obj pin) {
        String fixed=pin.stringOrNull("publishedAt");
        if (publishedAt == null ? fixed != null : fixed == null || !publishedAt.equals(Instant.parse(fixed))) return false;
        // Existing instant-only pools keep their original interpretation.
        if (!pin.node().has("eligibilityBasis")) return publishedAt != null;
        return basis.equals(pin.string("eligibilityBasis")) && availableAt.equals(Instant.parse(pin.string("availableAt")))
                && java.util.Objects.equals(publishedDate == null ? null : publishedDate.toString(), pin.stringOrNull("publishedDate"));
    }

    public static Instant available(tools.jackson.databind.JsonNode source) {
        if (source.path("publishedAt").isString()) return Instant.parse(source.path("publishedAt").asString());
        if (!"first_observed".equals(source.path("eligibilityBasis").asString()) || !source.path("publishedDate").isString())
            throw new IllegalArgumentException("source_clock_unavailable");
        LocalDate.parse(source.path("publishedDate").asString());
        return Instant.parse(source.path("availableAt").asString());
    }
}
