package com.zoop.briefing.query;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.StrictJson;
import java.nio.file.Path;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;

/**
 * Exact retained-result registration, separate from native graph registration.
 * It proves file/DB identity only; document grants remain the caller's current
 * authority and no native/S3/semantic-verification receipt is manufactured.
 */
public final class SavedBriefingBasisAuthority {
    private final JdbcTemplate jdbc;
    private final Path root;
    private final String cachePrefix = "retained-briefing-basis:" + java.util.UUID.randomUUID() + ":";

    public SavedBriefingBasisAuthority(JdbcTemplate jdbc, Path root) {
        this.jdbc = jdbc;
        this.root = root;
    }

    public boolean allows(JsonNode payload, JsonNode snapshot) {
        if (payload == null || snapshot == null) return false;
        if (!snapshot.has("retainedBasis")) return true;
        try {
            read(payload, snapshot);
            return true;
        } catch (RuntimeException unavailable) {
            return false;
        }
    }

    public boolean allowsCandidate(JsonNode payload, JsonNode snapshot, JsonNode candidate) {
        if (payload == null || snapshot == null) return false;
        if (!snapshot.has("retainedBasis")) return true;
        try {
            var basis = read(payload, snapshot);
            return Integer.valueOf(1).equals(jdbc.queryForObject("""
                SELECT count(*) FROM briefing_personal_pools p,
                    LATERAL jsonb_array_elements(p.snapshot->'candidates') c
                WHERE p.id=? AND p.round_id=? AND c=?::jsonb
                """, Integer.class, basis.string("poolId"), basis.string("roundId"), candidate.toString()));
        } catch (RuntimeException unavailable) {
            return false;
        }
    }

    public void require(JsonNode payload, JsonNode snapshot, JsonNode declared, String sourceManifestSha256) {
        var basis = read(payload, snapshot);
        if (!declared.equals(snapshot.path("retainedBasis"))
                || !basis.string("sourceManifestSha256").equals(sourceManifestSha256))
            throw new IllegalArgumentException("retained_basis_binding_changed");
    }

    private StrictJson.Obj read(JsonNode payload, JsonNode snapshot) {
        String key = cachePrefix + com.zoop.common.json.Canonical.sha256(payload.toString()+"\n"+snapshot.toString());
        return com.zoop.common.request.ReadScope.memo(key, () -> readNow(payload, snapshot));
    }

    private StrictJson.Obj readNow(JsonNode payload, JsonNode snapshot) {
        if (root == null || !payload.path("graphVersion").isNull())
            throw new IllegalArgumentException("retained_basis_requires_no_graph");
        var pin = StrictJson.Obj.of(snapshot.get("retainedBasis")).exactly(Set.of("artifactId", "sha256"));
        String sha = pin.string("sha256");
        if (!StrictJson.SHA256.matcher(sha).matches()
                || !pin.string("artifactId").equals("retained-basis-" + sha))
            throw new IllegalArgumentException("retained_basis_pin_invalid");
        var row = jdbc.queryForMap("SELECT kind,storage_uri,sha256,bytes FROM artifacts WHERE id=?", pin.string("artifactId"));
        if (!"briefing_input".equals(row.get("kind")) || !sha.equals(row.get("sha256")))
            throw new IllegalArgumentException("retained_basis_artifact_changed");
        byte[] raw = ArtifactFileStore.at(root).readVerified(row.get("storage_uri").toString(), sha,
                ((Number) row.get("bytes")).longValue());
        var basis = StrictJson.parseObject(raw).exactly(Set.of("schemaVersion", "sourceManifestSha256",
                "roundId", "cutoff", "payload", "snapshot", "poolId", "pool", "provenance"));
        if (!"briefing-retained-result-basis-v1".equals(basis.string("schemaVersion"))
                || !StrictJson.SHA256.matcher(basis.string("sourceManifestSha256")).matches()
                || !basis.string("roundId").equals(payload.path("id").asString())
                || !basis.string("cutoff").equals(payload.path("dataWindow").path("end").asString()))
            throw new IllegalArgumentException("retained_basis_identity_changed");
        var origin = basis.object("provenance").exactly(Set.of("origin", "nativeGraphRegistration", "newSemanticVerification"));
        if (!"retained-generated-results".equals(origin.string("origin"))
                || !"not-performed".equals(origin.string("nativeGraphRegistration"))
                || !"not-performed".equals(origin.string("newSemanticVerification")))
            throw new IllegalArgumentException("retained_basis_origin_changed");
        // PostgreSQL JSONB equality preserves real numeric values without
        // inventing a Python/Java float-canonicalization equivalence.
        Integer matching = jdbc.queryForObject("""
            SELECT count(*) FROM briefing_rounds r JOIN briefing_personal_pools p ON p.round_id=r.id
            WHERE r.id=? AND r.graph_version_id IS NULL AND r.window_to=?::timestamptz
            AND r.published_payload=?::jsonb AND r.published_payload=?::jsonb
            AND r.public_snapshot=?::jsonb AND r.public_snapshot-'retainedBasis'=?::jsonb
            AND r.payload_sha256=encode(sha256(convert_to(r.published_payload::text,'UTF8')),'hex')
            AND p.id=? AND p.snapshot=?::jsonb
            AND p.input_sha256=p.snapshot->>'inputSha256'
            AND p.snapshot_sha256=encode(sha256(convert_to(p.snapshot::text,'UTF8')),'hex')
            """, Integer.class, basis.string("roundId"), basis.string("cutoff"),
                payload.toString(), basis.raw("payload").toString(), snapshot.toString(),
                basis.raw("snapshot").toString(), basis.string("poolId"), basis.raw("pool").toString());
        if (!Integer.valueOf(1).equals(matching))
            throw new IllegalArgumentException("retained_basis_database_changed");
        return basis;
    }
}
