package com.zoop.briefing.replay;

import com.zoop.document.evidence.config.DocumentReadProperties;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.web.context.support.GenericWebApplicationContext;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Boundary rejection is exercised without connecting to any nonlocal or production database. */
class BriefingReplayBoundaryTest {
    @Test
    void onlyExplicitLoopbackAndDisposableReplayDatabaseUrlsAreAccepted() {
        for (String host : new String[] {"127.0.0.1", "localhost", "[::1]"}) {
            assertDoesNotThrow(() -> BriefingReplayGuard.jdbcUrl("jdbc:postgresql://" + host + ":5432/zoop_briefing_replay_test?currentSchema=synthetic,public"));
        }
        for (String url : new String[] {"jdbc:postgresql://db.example.invalid/zoop_briefing_replay_test",
                "jdbc:postgresql://127.0.0.1/zoop_production", "jdbc:postgresql://0.0.0.0/briefing_replay",
                "jdbc:postgresql://user:password@localhost/briefing_replay", "jdbc:h2:mem:briefing_replay",
                "jdbc:postgresql://127.0.0.1:5432/briefing_replay/another_database", "jdbc:postgresql:briefing_replay"}) {
            assertThrows(IllegalStateException.class, () -> BriefingReplayGuard.jdbcUrl(url), url);
        }
    }

    @Test
    void ordinaryReadSettingsRemainDisabledWithoutOpeningDatabase() {
        var jdbc = mock(JdbcTemplate.class);
        var settings = new MockEnvironment();
        assertNotNull(new BriefingReplayConfiguration().briefingReplayReadPolicy(settings, jdbc, new DocumentReadProperties(null, null)));
        verifyNoInteractions(jdbc);
    }

    @Test
    void replayReadCannotActivateForProductionProfileOrWildcardAddress() {
        var jdbc = mock(JdbcTemplate.class);
        for (boolean localProfile : new boolean[] {false, true}) {
            var env = new MockEnvironment().withProperty("zoop.briefing.replay.read-enabled", "true")
                    .withProperty("server.address", localProfile ? "0.0.0.0" : "127.0.0.1")
                    .withProperty("spring.datasource.url", "jdbc:postgresql://127.0.0.1/briefing_replay");
            env.setActiveProfiles(localProfile ? "local" : "production");
            assertThrows(IllegalStateException.class, () -> new BriefingReplayConfiguration()
                    .briefingReplayReadPolicy(env, jdbc, new DocumentReadProperties(null, null)));
        }
        verifyNoInteractions(jdbc);
    }

    @Test
    void importRunnerCannotRunInsideWebServingContext() {
        var env = new MockEnvironment();
        env.setActiveProfiles("local");
        var context = new GenericWebApplicationContext();
        try {
            assertThrows(IllegalStateException.class, () -> new BriefingReplayConfiguration()
                    .briefingReplayImportRunner(env, context, mock(JdbcTemplate.class), null));
        } finally { context.close(); }
    }
}
