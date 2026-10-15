package com.zoop.auth.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;

@Repository
public class JdbcMemberAuthRepository implements MemberAuthRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcMemberAuthRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<MemberAuthRow> findByEmailKey(String emailKey) {
        var rows = jdbc.query("""
                SELECT id, status, password_hash FROM members WHERE email_key = :emailKey
                """, new MapSqlParameterSource("emailKey", emailKey),
                (rs, index) -> new MemberAuthRow(rs.getString("id"),
                        rs.getString("status"), rs.getString("password_hash")));
        return rows.stream().findFirst();
    }

    @Override
    public Optional<MemberAuthRow> findById(String id) {
        var rows = jdbc.query("SELECT id, status, password_hash FROM members WHERE id = :id",
                new MapSqlParameterSource("id", id),
                (rs, index) -> new MemberAuthRow(rs.getString("id"),
                        rs.getString("status"), rs.getString("password_hash")));
        return rows.stream().findFirst();
    }

    @Override
    public Optional<MemberLinkTargetRow> findLinkTargetById(String id) {
        var rows = jdbc.query("SELECT id, status, email_key FROM members WHERE id = :id",
                new MapSqlParameterSource("id", id),
                (rs, index) -> new MemberLinkTargetRow(rs.getString("id"),
                        rs.getString("status"), rs.getString("email_key")));
        return rows.stream().findFirst();
    }

    @Override
    public boolean insertSocialMember(String id, String analyticsKey, String email, String emailKey,
            String displayName, String signupProvider, Instant createdAt) {
        if (!"google".equals(signupProvider) && !"kakao".equals(signupProvider)) {
            throw new IllegalArgumentException("Unsupported social signup provider");
        }
        int inserted = jdbc.update("""
                    INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                         password_hash, signup_method, status, mode, investor,
                                         completed, tutorial_completed, settings_version,
                                         created_at, updated_at, blocked_at)
                    VALUES (:id, :analyticsKey, :email, :emailKey, :displayName,
                            NULL, :provider, 'active', NULL, NULL,
                            false, false, 1, :at, :at, NULL)
                    ON CONFLICT (email_key) DO NOTHING
                    """, new MapSqlParameterSource()
                    .addValue("id", id).addValue("analyticsKey", analyticsKey)
                    .addValue("email", email).addValue("emailKey", emailKey)
                    .addValue("displayName", displayName).addValue("provider", signupProvider)
                    .addValue("at", Timestamp.from(createdAt)));
        return inserted == 1;
    }

    @Override
    public void insertEmailMember(String id, String analyticsKey, String email,
            String emailKey, String displayName, String passwordHash, Instant createdAt) {
        int inserted = jdbc.update("""
                    INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                         password_hash, signup_method, status, mode, investor,
                                         completed, tutorial_completed, settings_version,
                                         created_at, updated_at, blocked_at)
                    VALUES (:id, :analyticsKey, :email, :emailKey, :displayName,
                            :passwordHash, 'email', 'active', NULL, NULL,
                            false, false, 1, :at, :at, NULL)
                    ON CONFLICT (email_key) DO NOTHING
                    """, new MapSqlParameterSource()
                    .addValue("id", id).addValue("analyticsKey", analyticsKey)
                    .addValue("email", email).addValue("emailKey", emailKey)
                    .addValue("displayName", displayName).addValue("passwordHash", passwordHash)
                    .addValue("at", Timestamp.from(createdAt)));
        if (inserted == 0) {
            throw new CustomException(ErrorCode.EMAIL_TAKEN);
        }
    }
}
