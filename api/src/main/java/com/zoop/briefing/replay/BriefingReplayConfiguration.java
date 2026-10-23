package com.zoop.briefing.replay;

import java.nio.file.Path;
import java.util.Arrays;
import com.zoop.document.evidence.config.DocumentReadProperties;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationListener;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.web.context.WebApplicationContext;

@Configuration(proxyBeanMethods = false)
public class BriefingReplayConfiguration {
    /** Ready is published after every runner, including the confirmed-company catalog runner, has completed. */
    @Bean
    @ConditionalOnProperty(prefix = "zoop.briefing.replay", name = "import-enabled", havingValue = "true")
    ApplicationListener<ApplicationReadyEvent> briefingReplayImportShutdown() {
        return event -> event.getApplicationContext().close();
    }

    @Bean
    BriefingReplayReadPolicy briefingReplayReadPolicy(Environment env, JdbcTemplate jdbc, DocumentReadProperties read) {
        boolean enabled = Boolean.parseBoolean(env.getProperty("zoop.briefing.replay.read-enabled", "false"));
        if (!enabled) return BriefingReplayReadPolicy.disabled();
        local(env);
        if (!BriefingReplayGuard.loopback(env.getProperty("server.address"))) BriefingReplayGuard.reject();
        BriefingReplayGuard.jdbcUrl(env.getProperty("spring.datasource.url"));
        return new BriefingReplayReadPolicy(true, jdbc, path(env, "manifest"), read.grantsPath());
    }

    @Bean
    @ConditionalOnProperty(prefix = "zoop.briefing.replay", name = "import-enabled", havingValue = "true")
    ApplicationRunner briefingReplayImportRunner(Environment env, ApplicationContext context, JdbcTemplate jdbc,
            PlatformTransactionManager transactions) {
        local(env);
        if (context instanceof WebApplicationContext) {
            throw new IllegalStateException("Briefing replay import requires web-application-type=none");
        }
        if (Boolean.parseBoolean(env.getProperty("zoop.document-import.enabled", "false"))
                || Boolean.parseBoolean(env.getProperty("zoop.document-analysis.enabled", "false"))) {
            throw new IllegalStateException("Briefing replay cannot run beside another document writer");
        }
        BriefingReplayGuard.jdbcUrl(env.getProperty("spring.datasource.url"));
        BriefingReplaySettings settings = new BriefingReplaySettings(path(env, "source"), path(env, "bundle"),
                path(env, "artifact-root"), path(env, "grants"), path(env, "manifest"),
                required(env, "expected-source-sha256"), required(env, "user-inbox-ref"),
                env.getProperty("zoop.briefing.replay.clocks") == null ? null : path(env, "clocks"),
                env.getProperty("zoop.briefing.replay.maximum-paid-calls", Integer.class, 400),
                env.getProperty("zoop.briefing.replay.budget-approval-ref"));
        return arguments -> {
            BriefingReplayImporter.ImportResult result = new BriefingReplayImporter(jdbc, transactions, settings,
                    env.getProperty("zoop.briefing.replay.continuity-enabled", Boolean.class, false)).importBundle();
            System.out.println("Briefing development replay imported: " + result.documents() + " documents, "
                    + result.roundIds().size() + " rounds; existing=" + result.alreadyImported());
        };
    }

    private static void local(Environment env) {
        if (!Arrays.asList(env.getActiveProfiles()).contains("local")) BriefingReplayGuard.reject();
    }
    private static Path path(Environment env, String name) { return Path.of(required(env, name)); }
    private static String required(Environment env, String name) {
        String value = env.getProperty("zoop.briefing.replay." + name);
        if (value == null || value.isBlank()) throw new IllegalStateException("Missing briefing replay setting: " + name);
        return value;
    }
}
