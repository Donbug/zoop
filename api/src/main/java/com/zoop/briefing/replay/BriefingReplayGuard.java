package com.zoop.briefing.replay;

import java.net.URI;
import java.util.Set;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;

/** Shared fail-closed development boundary, checked against the live connection rather than an assumed test profile. */
public final class BriefingReplayGuard {
    private BriefingReplayGuard() { }

    public static void database(JdbcTemplate jdbc) {
        jdbc.execute((ConnectionCallback<Void>) connection -> {
            jdbcUrl(connection.getMetaData().getURL());
            String database = connection.getCatalog();
            if (database == null || !database.matches("[a-z0-9_]*briefing_replay[a-z0-9_]*")) reject();
            return null;
        });
    }

    public static void jdbcUrl(String value) {
        try {
            if (value == null || !value.startsWith("jdbc:postgresql://")) reject();
            URI uri = URI.create(value.substring(5));
            if (!loopback(uri.getHost()) || uri.getUserInfo() != null || uri.getPath() == null
                    || !uri.getPath().matches("/[a-z0-9_]*briefing_replay[a-z0-9_]*")) reject();
        } catch (RuntimeException error) { reject(); }
    }

    public static boolean loopback(String host) {
        return host != null && Set.of("127.0.0.1", "localhost", "::1", "[::1]").contains(host);
    }

    static void reject() { throw new IllegalStateException("Briefing replay requires an explicit local loopback disposable database"); }
}
