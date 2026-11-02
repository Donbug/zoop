package com.zoop.briefing.personal;

import com.zoop.common.json.StrictJson;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;
import java.util.Optional;

@Repository
public class PersonalBriefingRepository {
    private final JdbcTemplate jdbc;
    public PersonalBriefingRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }
    public Optional<JsonNode> pool(String roundId) {
        return jdbc.query("""
            SELECT snapshot FROM briefing_personal_pools p JOIN briefing_rounds r ON r.id=p.round_id WHERE round_id=?
                AND snapshot->>'publicationPayloadSha256'=r.payload_sha256
                AND snapshot_sha256=encode(sha256(convert_to(snapshot::text,'UTF8')),'hex')
            ORDER BY p.created_at DESC,p.id COLLATE "C" LIMIT 1
            """, (r, i) -> StrictJson.parseObject(r.getString(1)).node(), roundId).stream().findFirst();
    }
}
