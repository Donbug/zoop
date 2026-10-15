package com.zoop.auth.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcSignupTermsRepository implements SignupTermsRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcSignupTermsRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public List<SignupTermRow> listCurrent(Instant at) {
        return jdbc.query("""
                SELECT t.id, COALESCE(v.required_snapshot, t.required) AS required, v.version
                FROM terms t
                LEFT JOIN term_versions v
                  ON v.term_id = t.id
                 AND v.approved_at <= :at
                 AND v.effective_at <= :at
                 AND (v.retired_at IS NULL OR v.retired_at > :at)
                WHERE t.created_at <= :at
                  AND (t.retired_at IS NULL OR t.retired_at > :at)
                ORDER BY t.id
                """, new MapSqlParameterSource("at", Timestamp.from(at)),
                (rs, index) -> new SignupTermRow(rs.getString("id"),
                        rs.getBoolean("required"), rs.getString("version")));
    }

    @Override
    public void recordAgreement(String memberId, String termId, String version,
            boolean accepted, Instant at) {
        jdbc.update("""
                INSERT INTO term_agreements
                  (member_id, term_id, term_version, accepted, accepted_at)
                VALUES (:memberId, :termId, :version, :accepted, :at)
                """, new MapSqlParameterSource()
                .addValue("memberId", memberId).addValue("termId", termId)
                .addValue("version", version).addValue("accepted", accepted)
                .addValue("at", Timestamp.from(at)));
    }
}
