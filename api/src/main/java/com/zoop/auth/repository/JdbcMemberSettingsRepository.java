package com.zoop.auth.repository;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcMemberSettingsRepository implements MemberSettingsRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcMemberSettingsRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<MemberSettingsRow> find(String memberId) {
        return read(memberId, false);
    }

    @Override
    public Optional<MemberSettingsRow> findForUpdate(String memberId) {
        return read(memberId, true);
    }

    private Optional<MemberSettingsRow> read(String memberId, boolean lock) {
        String suffix = lock ? " FOR UPDATE" : "";
        var params = new MapSqlParameterSource("memberId", memberId);
        var rows = jdbc.query("""
                SELECT mode, investor, completed, tutorial_completed, settings_version
                  FROM members WHERE id = :memberId
                """ + suffix, params, (rs, index) -> new MemberSettingsRow(
                rs.getString("mode"), (Boolean) rs.getObject("investor"),
                rs.getBoolean("completed"), rs.getBoolean("tutorial_completed"),
                rs.getLong("settings_version"), List.of()));
        if (rows.isEmpty()) return Optional.empty();
        var ids = jdbc.query("""
                SELECT company_id FROM member_watchlist
                 WHERE member_id = :memberId ORDER BY position, company_id
                """, params, (rs, index) -> rs.getString("company_id"));
        var row = rows.getFirst();
        return Optional.of(new MemberSettingsRow(row.mode(), row.investor(), row.completed(),
                row.tutorialCompleted(), row.version(), List.copyOf(ids)));
    }

    @Override
    public void update(String memberId, String mode, Boolean investor, boolean completed,
            boolean tutorialCompleted, long expectedVersion, long nextVersion) {
        int changed = jdbc.update("""
                UPDATE members SET mode = :mode, investor = :investor, completed = :completed,
                       tutorial_completed = :tutorialCompleted, settings_version = :nextVersion,
                       updated_at = now()
                 WHERE id = :memberId AND settings_version = :expectedVersion
                """, new MapSqlParameterSource().addValue("memberId", memberId)
                .addValue("mode", mode).addValue("investor", investor).addValue("completed", completed)
                .addValue("tutorialCompleted", tutorialCompleted).addValue("expectedVersion", expectedVersion)
                .addValue("nextVersion", nextVersion));
        if (changed != 1) throw new IllegalStateException("Settings row changed while locked");
    }

    @Override
    public boolean companiesExist(Iterable<String> companyIds) {
        var ids = new ArrayList<String>();
        companyIds.forEach(ids::add);
        if (ids.isEmpty()) return true;
        Integer count = jdbc.queryForObject("SELECT count(*) FROM companies WHERE id IN (:ids)",
                new MapSqlParameterSource("ids", ids), Integer.class);
        return count != null && count == ids.size();
    }

    @Override
    public void replaceWatchlist(String memberId, Iterable<String> companyIds) {
        jdbc.update("DELETE FROM member_watchlist WHERE member_id = :memberId",
                new MapSqlParameterSource("memberId", memberId));
        var params = new ArrayList<MapSqlParameterSource>();
        int position = 0;
        for (String id : companyIds) {
            params.add(new MapSqlParameterSource().addValue("memberId", memberId)
                    .addValue("companyId", id).addValue("position", position++));
        }
        if (!params.isEmpty()) {
            jdbc.batchUpdate("""
                    INSERT INTO member_watchlist (member_id, company_id, position)
                    VALUES (:memberId, :companyId, :position)
                    """, params.toArray(MapSqlParameterSource[]::new));
        }
    }
}
