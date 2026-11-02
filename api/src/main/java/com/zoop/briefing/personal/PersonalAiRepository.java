package com.zoop.briefing.personal;
import com.zoop.common.json.StrictJson;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;
import java.util.Optional;

@Repository
public class PersonalAiRepository {
    public record Saved(JsonNode input,JsonNode result,JsonNode proof) {}
    private final JdbcTemplate jdbc;
    public PersonalAiRepository(JdbcTemplate jdbc){this.jdbc=jdbc;}
    public Optional<Saved> find(String memberId,String roundId,JsonNode basis) {
        return jdbc.query("""
            SELECT input_snapshot,result,provider_proof FROM briefing_personal_analyses
            WHERE member_id=? AND round_id=? AND selection_basis=?::jsonb
                AND result_sha256=encode(sha256(convert_to(result::text,'UTF8')),'hex')
            ORDER BY created_at DESC,result_version COLLATE "C" DESC LIMIT 1
            """,(r,i)->new Saved(StrictJson.parseObject(r.getString(1)).node(),StrictJson.parseObject(r.getString(2)).node(),
                tools.jackson.databind.json.JsonMapper.builder().build().readTree(r.getString(3))),memberId,roundId,basis.toString()).stream().findFirst();
    }
}
