package com.zoop.briefing.reconstruction;

import com.zoop.briefing.replay.BriefingReplayGuard;
import java.nio.file.Path;
import java.util.Arrays;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationListener;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.context.WebApplicationContext;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.briefing.graph-reconstruction", name = "enabled", havingValue = "true")
public class BriefingGraphReconstructionConfiguration {
    @Bean
    ApplicationRunner reconstructStoredBriefingGraphs(Environment env, ApplicationContext context,
            JdbcTemplate jdbc, BriefingGraphReconstructor reconstructor) {
        if (!Arrays.asList(env.getActiveProfiles()).contains("local") || context instanceof WebApplicationContext)
            throw new IllegalStateException("Reconstruction requires an explicit local non-web run");
        BriefingReplayGuard.jdbcUrl(env.getProperty("spring.datasource.url"));
        Path root = Path.of(env.getRequiredProperty("zoop.graph.snapshot.artifact-root"));
        return args -> {
            var ids = jdbc.queryForList("SELECT id FROM briefing_rounds WHERE status='published' AND published_at IS NOT NULL AND graph_version_id IS NULL AND public_snapshot ? 'replay' ORDER BY scheduled_at,id", String.class);
            for (String id : ids) System.out.println("Briefing graph reconstructed: " + id + " -> " + reconstructor.reconstruct(id, root));
        };
    }
    @Bean
    ApplicationListener<ApplicationReadyEvent> reconstructionShutdown() {
        return event -> event.getApplicationContext().close();
    }
}
