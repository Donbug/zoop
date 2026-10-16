package com.zoop.portfolio.repository;

import java.sql.Timestamp;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcPortfolioConnectionRepository implements PortfolioConnectionRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcPortfolioConnectionRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public boolean lockMember(String memberId) {
        List<String> rows = jdbc.query("SELECT id FROM members WHERE id = :memberId FOR UPDATE",
                new MapSqlParameterSource("memberId", memberId), (rs, index) -> rs.getString("id"));
        return !rows.isEmpty();
    }

    @Override
    public Optional<PortfolioConnectionRow> findConnection(String memberId) {
        return find("SELECT connection_id, mock_portfolio_id, connected_at FROM member_portfolio_connections "
                + "WHERE member_id = :memberId", new MapSqlParameterSource("memberId", memberId));
    }

    @Override
    public Optional<PortfolioConnectionRow> findConnection(String memberId, String connectionId) {
        return find("SELECT connection_id, mock_portfolio_id, connected_at FROM member_portfolio_connections "
                + "WHERE member_id = :memberId AND connection_id = :connectionId",
                new MapSqlParameterSource().addValue("memberId", memberId).addValue("connectionId", connectionId));
    }

    @Override
    public Optional<PortfolioIdempotencyRow> findIdempotency(String memberId, String idempotencyKey) {
        var rows = jdbc.query("""
                SELECT mock_portfolio_id, connection_id, connected_at FROM member_portfolio_idempotency
                 WHERE member_id = :memberId AND idempotency_key = :idempotencyKey
                """, new MapSqlParameterSource().addValue("memberId", memberId)
                .addValue("idempotencyKey", idempotencyKey), (rs, index) -> new PortfolioIdempotencyRow(
                        rs.getString("mock_portfolio_id"), rs.getString("connection_id"),
                        rs.getTimestamp("connected_at").toInstant()));
        return rows.stream().findFirst();
    }

    @Override
    public void saveConnection(String memberId, PortfolioConnectionRow connection) {
        jdbc.update("""
                INSERT INTO member_portfolio_connections (member_id, connection_id, mock_portfolio_id, connected_at)
                VALUES (:memberId, :connectionId, :mockPortfolioId, :connectedAt)
                ON CONFLICT (member_id) DO UPDATE SET
                    connection_id = EXCLUDED.connection_id,
                    mock_portfolio_id = EXCLUDED.mock_portfolio_id,
                    connected_at = EXCLUDED.connected_at
                """, params(memberId, connection.connectionId(), connection.mockPortfolioId(), connection.connectedAt()));
    }

    @Override
    public void saveIdempotency(String memberId, String idempotencyKey, PortfolioIdempotencyRow record) {
        jdbc.update("""
                INSERT INTO member_portfolio_idempotency
                    (member_id, idempotency_key, mock_portfolio_id, connection_id, connected_at)
                VALUES (:memberId, :idempotencyKey, :mockPortfolioId, :connectionId, :connectedAt)
                """, new MapSqlParameterSource().addValue("memberId", memberId)
                .addValue("idempotencyKey", idempotencyKey).addValue("mockPortfolioId", record.mockPortfolioId())
                .addValue("connectionId", record.connectionId()).addValue("connectedAt", Timestamp.from(record.connectedAt())));
    }

    @Override
    public boolean deleteConnection(String memberId, String connectionId) {
        return jdbc.update("DELETE FROM member_portfolio_connections "
                + "WHERE member_id = :memberId AND connection_id = :connectionId",
                new MapSqlParameterSource().addValue("memberId", memberId).addValue("connectionId", connectionId)) == 1;
    }

    private Optional<PortfolioConnectionRow> find(String sql, MapSqlParameterSource params) {
        var rows = jdbc.query(sql, params, (rs, index) -> new PortfolioConnectionRow(
                rs.getString("connection_id"), rs.getString("mock_portfolio_id"),
                rs.getTimestamp("connected_at").toInstant()));
        return rows.stream().findFirst();
    }

    private static MapSqlParameterSource params(String memberId, String connectionId,
            String mockPortfolioId, java.time.Instant connectedAt) {
        return new MapSqlParameterSource().addValue("memberId", memberId)
                .addValue("connectionId", connectionId).addValue("mockPortfolioId", mockPortfolioId)
                .addValue("connectedAt", Timestamp.from(connectedAt));
    }
}
