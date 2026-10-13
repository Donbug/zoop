package com.zoop.auth.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcTermRepository implements TermRepository {
    private static final String QUERY = """
            SELECT t.id,
                   COALESCE(v.title_snapshot, t.title) AS title,
                   COALESCE(v.required_snapshot, t.required) AS required,
                   v.version,
                   v.body
            FROM terms t
            LEFT JOIN term_versions v
              ON v.term_id = t.id
             AND v.approved_at <= :asOf
             AND v.effective_at <= :asOf
             AND (v.retired_at IS NULL OR :asOf < v.retired_at)
            WHERE t.created_at <= :asOf
              AND (t.retired_at IS NULL OR :asOf < t.retired_at)
              AND t.id > :afterId
            ORDER BY t.id
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcTermRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public List<TermRow> listAt(Instant asOf, String afterId, Long fetchCount) {
        var parameters = new MapSqlParameterSource()
                .addValue("asOf", Timestamp.from(asOf))
                .addValue("afterId", afterId);
        String sql = QUERY;
        if (fetchCount != null) {
            sql += "LIMIT :fetchCount";
            parameters.addValue("fetchCount", fetchCount);
        }
        return jdbc.query(sql, parameters, (result, index) -> new TermRow(
                result.getString("id"),
                result.getString("title"),
                result.getBoolean("required"),
                result.getString("version"),
                result.getString("body")));
    }
}
