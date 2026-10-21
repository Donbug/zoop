package com.zoop.telemetry;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class TelemetryRepository {
    private final NamedParameterJdbcTemplate jdbc;
    public TelemetryRepository(NamedParameterJdbcTemplate jdbc) { this.jdbc = jdbc; }

    public int record(String principal, String key, String digest, List<Event> events, Instant now) {
        var params = new MapSqlParameterSource().addValue("principal", principal).addValue("key", key)
                .addValue("digest", digest).addValue("accepted", events.size())
                .addValue("now", Timestamp.from(now));
        int inserted = jdbc.update("""
                INSERT INTO telemetry_batches (principal_key, idempotency_key, payload_sha256, accepted, created_at)
                VALUES (:principal, :key, :digest, :accepted, :now) ON CONFLICT DO NOTHING
                """, params);
        if (inserted == 0) {
            String oldDigest = jdbc.queryForObject("SELECT payload_sha256 FROM telemetry_batches "
                    + "WHERE principal_key=:principal AND idempotency_key=:key", params, String.class);
            if (!digest.equals(oldDigest)) throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
            return jdbc.queryForObject("SELECT accepted FROM telemetry_batches "
                    + "WHERE principal_key=:principal AND idempotency_key=:key", params, Integer.class);
        }
        for (Event event : events) {
            jdbc.update("""
                    INSERT INTO telemetry_events (principal_key,event_type,screen,target_id,round_id,view_id,occurred_at)
                    VALUES (:principal,:type,:screen,:target,:round,:view,:now)
                    """, new MapSqlParameterSource().addValue("principal", principal)
                    .addValue("type", event.type()).addValue("screen", event.screen())
                    .addValue("target", event.targetId()).addValue("round", event.roundId())
                    .addValue("view", event.viewId()).addValue("now", Timestamp.from(event.occurredAt())));
        }
        return events.size();
    }
    public record Event(String type, String screen, String targetId, String roundId, String viewId, Instant occurredAt) { }
}
