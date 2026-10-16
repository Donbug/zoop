package com.zoop.briefing.replay;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;

/** Optional local read permission for an imported development replay; it never authorizes an operational graph. */
public final class BriefingReplayReadPolicy {
    private final boolean enabled;
    private final JdbcTemplate jdbc;
    private final Path manifest;
    private final Path grants;

    public BriefingReplayReadPolicy(boolean enabled, JdbcTemplate jdbc, Path manifest, Path grants) {
        if (enabled && (jdbc == null || manifest == null || grants == null || !manifest.isAbsolute()
                || !grants.isAbsolute() || !manifest.equals(manifest.normalize()) || !grants.equals(grants.normalize()))) {
            throw new IllegalArgumentException("Briefing replay read requires explicit normalized private manifest and grants paths");
        }
        this.enabled = enabled; this.jdbc = jdbc; this.manifest = manifest; this.grants = grants;
    }

    public static BriefingReplayReadPolicy disabled() { return new BriefingReplayReadPolicy(false, null, null, null); }

    public static boolean marked(BriefingRound row) {
        return row.publicSnapshot() != null && row.publicSnapshot().has("replay");
    }

    public boolean permits(BriefingRound row) {
        if (!enabled || !marked(row) || row.graphVersion() != null) return false;
        try {
            BriefingReplayGuard.database(jdbc);
            if (Files.size(manifest) > 8_000_000 || Files.size(grants) > 1_000_000) return false;
            StrictJson.Obj saved = StrictJson.parseObject(Files.readAllBytes(manifest));
            StrictJson.Obj marker = StrictJson.Obj.of(row.publicSnapshot()).object("replay");
            String scope = saved.string("scope");
            if (!List.of("development_replay", "publication_clock_simulation").contains(scope)
                    || !scope.equals(marker.string("scope"))) return false;
            for (String field : List.of("runId", "sourceFileSha256", "bundleSha256", "userInboxRef")) {
                if (!saved.string(field).equals(marker.string(field))) return false;
            }
            if ("publication_clock_simulation".equals(scope)
                    && (!saved.string("clockFileSha256").equals(marker.string("clockFileSha256"))
                        || !marker.bool("retrospectiveBodies") || marker.bool("operationalCollectionGate"))) return false;
            if (!saved.string("grantsSha256").equals(Canonical.sha256(Files.readAllBytes(grants)))) return false;
            for (StrictJson.Obj round : saved.objects("rounds")) {
                if (!round.string("id").equals(row.id())) continue;
                if (round.isNull("payloadSha256")) {
                    if (row.publishedAt() != null || !"publication_clock_simulation".equals(scope)) return false;
                    Integer count = jdbc.queryForObject("""
                            SELECT count(*) FROM briefing_rounds WHERE id=? AND published_at IS NULL AND published_payload IS NULL
                                AND graph_version_id IS NULL AND encode(sha256(convert_to(public_snapshot::text,'UTF8')),'hex')=?
                            """, Integer.class, row.id(), round.string("publicSnapshotSha256"));
                    return Integer.valueOf(1).equals(count); // Header/mode disclosure only: it grants no published content.
                }
                Integer count = jdbc.queryForObject("""
                        SELECT count(*) FROM briefing_rounds WHERE id=? AND graph_version_id IS NULL
                        AND payload_sha256=? AND payload_sha256=encode(sha256(convert_to(published_payload::text,'UTF8')),'hex')
                        AND encode(sha256(convert_to(public_snapshot::text,'UTF8')),'hex')=?
                        """, Integer.class, row.id(), round.string("payloadSha256"), round.string("publicSnapshotSha256"));
                return Integer.valueOf(1).equals(count);
            }
            return false;
        } catch (Exception invalidOrUnavailable) { return false; }
    }
}
