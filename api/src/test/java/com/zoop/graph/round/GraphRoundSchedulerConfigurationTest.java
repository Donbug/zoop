package com.zoop.graph.round;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.util.LinkedHashMap;
import java.util.Map;

import javax.sql.DataSource;

import com.zoop.admin.jobs.AnalysisJobService;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository;
import com.zoop.ai.config.AiHandoffReadClientConfiguration;
import com.zoop.ai.config.AiRoundClientConfiguration;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.importer.GraphHandoffRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.Mockito;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.ObjectMapper;

/** The scheduler's wiring: it needs the round client and the analyze_plan queue on top of the bridge's requirements. */
class GraphRoundSchedulerConfigurationTest {
    @TempDir
    Path temp;
    private final Map<String, String> valid = new LinkedHashMap<>();

    @BeforeEach
    void setUp() throws IOException {
        Path base = temp.toRealPath();
        Path cli = Files.writeString(base.resolve("zoop-ai-ingest"), "#!/bin/sh\n");
        Files.setPosixFilePermissions(cli, PosixFilePermissions.fromString("rwx------"));
        valid.put("ZOOP_GRAPH_ROUND_ENABLED", "true");
        valid.put("ZOOP_GRAPH_SNAPSHOT_SOURCE", "artifact");
        valid.put("ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT", Files.createDirectory(base.resolve("artifacts")).toString());
        valid.put("ZOOP_GRAPH_ROUND_INGESTION_CLI", cli.toString());
        valid.put("ZOOP_GRAPH_ROUND_INGESTION_STATE_DIR", Files.createDirectory(base.resolve("ingestion")).toString());
        valid.put("ZOOP_GRAPH_ROUND_INGESTION_SOURCES", Files.writeString(base.resolve("sources.json"), "{}").toString());
        valid.put("ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED", "true");
        valid.put("ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL", "https://ai.internal.example");
        valid.put("ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN", "read-token-0123456789abcdefghijklmnopqrstuvwxyz");
        valid.put("ZOOP_AI_ROUND_CLIENT_ENABLED", "true");
        valid.put("ZOOP_AI_ROUND_CLIENT_BASE_URL", "https://ai.internal.example");
        valid.put("ZOOP_AI_ROUND_CLIENT_TOKEN", "round-token-0123456789abcdefghijklmnopqrstuvwxyz");
        valid.put("ZOOP_ANALYSIS_ANALYZE_PLAN_ENABLED", "true");
        valid.put("ZOOP_GRAPH_ROUND_INTERVAL", "PT5S");
    }

    private static void isolate(ConfigurableApplicationContext context) {
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
    }

    private WebApplicationContextRunner runner() {
        return new WebApplicationContextRunner()
                .withInitializer(GraphRoundSchedulerConfigurationTest::isolate)
                .withInitializer(new ConfigDataApplicationContextInitializer())
                .withBean(DocumentRegistryRepository.class, () -> Mockito.mock(DocumentRegistryRepository.class))
                .withBean(GraphHandoffRepository.class, () -> Mockito.mock(GraphHandoffRepository.class))
                .withBean(GraphRoundRepository.class, InMemoryGraphRoundRepository::new)
                .withBean(TransactionOperations.class, TransactionOperations::withoutTransaction)
                .withBean(DataSource.class, () -> Mockito.mock(DataSource.class))
                .withBean(NamedParameterJdbcTemplate.class, () -> Mockito.mock(NamedParameterJdbcTemplate.class))
                .withBean(AnalysisJobService.class, () -> Mockito.mock(AnalysisJobService.class))
                .withBean(JdbcAnalysisJobRepository.class, () -> Mockito.mock(JdbcAnalysisJobRepository.class))
                .withBean(ObjectMapper.class, ObjectMapper::new)
                .withBean(Clock.class, Clock::systemUTC)
                .withUserConfiguration(AiHandoffReadClientConfiguration.class, AiRoundClientConfiguration.class,
                        GraphRoundImportConfiguration.class, GraphRoundSchedulerConfiguration.class);
    }

    private String[] with(String... extra) {
        Map<String, String> changed = new LinkedHashMap<>(valid);
        for (int i = 0; i + 1 < extra.length; i += 2) {
            if (extra[i + 1] == null) changed.remove(extra[i]);
            else changed.put(extra[i], extra[i + 1]);
        }
        return changed.entrySet().stream().map(entry -> entry.getKey() + "=" + entry.getValue()).toArray(String[]::new);
    }

    @Test
    void disabledRegistersNoSchedulerAndTheOverviewSeesNoStatus() {
        runner().withPropertyValues(with("ZOOP_GRAPH_ROUND_ENABLED", "false")).run(context -> {
            assertNull(context.getStartupFailure());
            assertTrue(context.getBeansOfType(GraphRoundScheduler.class).isEmpty());
            assertTrue(context.getBeansOfType(GraphRoundStatus.class).isEmpty());
            assertTrue(context.getBeansOfType(GraphRoundClock.class).isEmpty());
        });
    }

    @Test
    void enabledWithTheRoundClientAndTheQueueCreatesTheSchedulerWhichIsTheOverviewsStatus() {
        runner().withPropertyValues(with()).run(context -> {
            assertNull(context.getStartupFailure());
            GraphRoundScheduler scheduler = context.getBean(GraphRoundScheduler.class);
            assertNotNull(context.getBean(GraphRoundWorker.class));
            assertNotNull(context.getBean(RoundBindingsSource.class));
            assertTrue(context.getBean(GraphRoundStatus.class).enabled());
            assertTrue(scheduler.nextSlotAt().isPresent());
            assertTrue(scheduler.isRunning(), "SmartLifecycle started with the context");
            GraphRoundProperties properties = context.getBean(GraphRoundProperties.class);
            assertEquals(java.time.Duration.ofSeconds(5), properties.interval());
            assertEquals(java.util.List.of(java.time.LocalTime.of(18, 5)), properties.freezeOnlySlots());
        });
    }

    @Test
    void aMissingRoundClientOrAnalyzePlanQueueOrABadCalendarFailsStartupNamingTheSetting() {
        runner().withPropertyValues(with("ZOOP_AI_ROUND_CLIENT_ENABLED", "false")).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().contains("zoop.ai.round-client.enabled"), failure.getMessage());
        });
        runner().withPropertyValues(with("ZOOP_ANALYSIS_ANALYZE_PLAN_ENABLED", "false")).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().contains("zoop.analysis.analyze-plan.enabled"), failure.getMessage());
        });
        runner().withPropertyValues(with("ZOOP_GRAPH_ROUND_FREEZE_ONLY", "09:35")).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.graph.round.freeze-only "), failure.getMessage());
        });
        runner().withPropertyValues(with("ZOOP_GRAPH_ROUND_ZONE", "Mars/Olympus")).run(context -> {
            Throwable failure = configurationFailure(context.getStartupFailure());
            assertNotNull(failure);
            assertTrue(failure.getMessage().startsWith("zoop.graph.round.zone "), failure.getMessage());
        });
    }

    private static Throwable configurationFailure(Throwable failure) {
        for (Throwable cause = failure; cause != null; cause = cause.getCause()) {
            if (cause instanceof GraphRoundConfigurationException) return cause;
        }
        return null;
    }
}
