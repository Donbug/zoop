package com.zoop.auth.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcSocialIdentityRepository implements SocialIdentityRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcSocialIdentityRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<SocialIdentityRow> findByProviderSubject(String provider, String providerSubject) {
        var rows = jdbc.query("""
                SELECT id, member_id, provider, provider_subject, linked_at
                FROM social_identities
                WHERE provider = :provider AND provider_subject = :providerSubject
                """, new MapSqlParameterSource()
                .addValue("provider", provider)
                .addValue("providerSubject", providerSubject),
                (rs, index) -> new SocialIdentityRow(rs.getString("id"), rs.getString("member_id"),
                        rs.getString("provider"), rs.getString("provider_subject"),
                        rs.getTimestamp("linked_at").toInstant()));
        return rows.stream().findFirst();
    }

    @Override
    public void insert(String id, String memberId, String provider, String providerSubject, Instant linkedAt) {
        jdbc.update("""
                INSERT INTO social_identities (id, member_id, provider, provider_subject, linked_at)
                VALUES (:id, :memberId, :provider, :providerSubject, :linkedAt)
                """, new MapSqlParameterSource()
                .addValue("id", id)
                .addValue("memberId", memberId)
                .addValue("provider", provider)
                .addValue("providerSubject", providerSubject)
                .addValue("linkedAt", Timestamp.from(linkedAt)));
    }
}
