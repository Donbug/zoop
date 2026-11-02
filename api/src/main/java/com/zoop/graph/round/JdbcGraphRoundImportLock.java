package com.zoop.graph.round;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Optional;

import javax.sql.DataSource;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A PostgreSQL session-level advisory lock on a connection of its own, held for the whole import (which runs several
 * transactions of its own and must not be nested in one). The connection goes back to the pool when the handle closes; if the
 * connection is lost the lock is gone with it, which is the failure the round's next attempt simply repeats.
 */
public final class JdbcGraphRoundImportLock implements GraphRoundImportLock {
    static final String KEY = "zoop-graph-round-import-v1";
    private static final Logger log = LoggerFactory.getLogger(JdbcGraphRoundImportLock.class);
    private final DataSource dataSource;

    public JdbcGraphRoundImportLock(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Optional<Held> tryAcquire() {
        Connection connection;
        try {
            connection = dataSource.getConnection();
        } catch (SQLException unavailable) {
            log.warn("graph round import lock: no connection: {}", unavailable.getClass().getSimpleName());
            return Optional.empty();
        }
        try {
            boolean taken;
            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT pg_try_advisory_lock(hashtextextended(?, 0))")) {
                statement.setString(1, KEY);
                try (ResultSet rs = statement.executeQuery()) {
                    taken = rs.next() && rs.getBoolean(1);
                }
            }
            if (!taken) {
                connection.close();
                return Optional.empty();
            }
        } catch (SQLException failure) {
            log.warn("graph round import lock could not be taken: {}", failure.getClass().getSimpleName());
            closeQuietly(connection);
            return Optional.empty();
        }
        return Optional.of(() -> {
            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT pg_advisory_unlock(hashtextextended(?, 0))")) {
                statement.setString(1, KEY);
                statement.execute();
            } catch (SQLException failure) {
                log.warn("graph round import lock could not be released cleanly: {}", failure.getClass().getSimpleName());
            } finally {
                closeQuietly(connection);
            }
        });
    }

    private static void closeQuietly(Connection connection) {
        try {
            connection.close();
        } catch (SQLException ignored) {
            // the pool evicts a broken connection
        }
    }
}
