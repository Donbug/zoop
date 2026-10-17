package com.zoop.briefing.replay;

import java.nio.file.Files;
import java.nio.file.Path;
import com.zoop.document.evidence.config.DocumentReadProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** The operator process may finish only after all startup runners; normal HTTP/read configurations stay running. */
class BriefingReplayShutdownTest {
    @TempDir Path directory;

    private ApplicationContextRunner context() {
        return new ApplicationContextRunner().withUserConfiguration(BriefingReplayConfiguration.class)
                .withBean(JdbcTemplate.class, () -> mock(JdbcTemplate.class))
                .withBean(PlatformTransactionManager.class, () -> mock(PlatformTransactionManager.class))
                .withBean(DocumentReadProperties.class, () -> new DocumentReadProperties(null, null));
    }

    @Test
    void ordinaryReadAndOtherImportFlagsDoNotInstallProcessShutdown() {
        context().withPropertyValues("zoop.document-import.enabled=true", "zoop.document-analysis.enabled=true")
                .run(context -> {
                    assertFalse(context.containsBean("briefingReplayImportShutdown"));
                    assertTrue(context.isActive());
                });
    }

    @Test
    void explicitReplayImportInstallsShutdownAndWaitsForApplicationReady() throws Exception {
        Path root = directory.toRealPath();
        Path source = Files.writeString(root.resolve("source.jsonl"), "{}\n");
        Path bundle = Files.writeString(root.resolve("bundle.json"), "{}");
        Path artifacts = Files.createDirectory(root.resolve("artifacts"));
        context().withInitializer(context -> context.getEnvironment().setActiveProfiles("local"))
                .withPropertyValues("zoop.briefing.replay.import-enabled=true",
                        "spring.datasource.url=jdbc:postgresql://127.0.0.1/zoop_briefing_replay_test",
                        "zoop.briefing.replay.source=" + source, "zoop.briefing.replay.bundle=" + bundle,
                        "zoop.briefing.replay.artifact-root=" + artifacts,
                        "zoop.briefing.replay.grants=" + root.resolve("grants.json"),
                        "zoop.briefing.replay.manifest=" + root.resolve("manifest.json"),
                        "zoop.briefing.replay.expected-source-sha256=" + "a".repeat(64),
                        "zoop.briefing.replay.user-inbox-ref=inbox/synthetic-shutdown-test.md")
                .run(context -> {
                    assertNotNull(context.getBean("briefingReplayImportShutdown"));
                    assertTrue(context.isActive());
                });
        var readyContext = mock(ConfigurableApplicationContext.class);
        var ready = mock(ApplicationReadyEvent.class);
        when(ready.getApplicationContext()).thenReturn(readyContext);
        var shutdown = new BriefingReplayConfiguration().briefingReplayImportShutdown();
        verifyNoInteractions(readyContext);
        shutdown.onApplicationEvent(ready);
        verify(readyContext, times(1)).close();
        verifyNoMoreInteractions(readyContext);
    }
}
