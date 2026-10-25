package com.zoop.admin.graph;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.Optional;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.JdbcGraphVersionRepository.Activation;
import org.junit.jupiter.api.Test;
import org.springframework.boot.convert.ApplicationConversionService;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class GraphAutoActivationSchedulerTest {
    private static final Instant START = Instant.parse("2026-10-26T00:05:00Z");
    private static final GraphVersionRecord IMPORTED = new GraphVersionRecord(
            "gv-2", 7, "snapshot", "artifact-2", "artifact://gv-2.json", "a".repeat(64), false);

    private final AdminGraphVersionService service = mock(AdminGraphVersionService.class);
    private final MovingClock clock = new MovingClock(START);
    private final GraphAutoActivationScheduler scheduler = new GraphAutoActivationScheduler(service, clock, Duration.ofMinutes(5));

    @Test
    void onlyVersionsImportedAfterItStartedAreCandidatesAndNothingIsTriedWithoutOne() {
        when(service.importedCandidate(START)).thenReturn(Optional.empty());
        clock.advance(Duration.ofMinutes(1));

        scheduler.runOnce();

        verify(service).importedCandidate(START);
        verify(service, never()).activateImported(any(), any(), anyString());
    }

    @Test
    void theCandidateIsActivatedWithTheStartTime() {
        when(service.importedCandidate(START)).thenReturn(Optional.of(IMPORTED));
        when(service.activateImported(eq(IMPORTED), eq(START), anyString()))
                .thenReturn(Optional.of(new Activation("gv-1", true, START.plusSeconds(15))));

        scheduler.runOnce();

        verify(service).activateImported(eq(IMPORTED), eq(START), anyString());
    }

    @Test
    void aRefusedVersionIsRetriedOnlyAfterRetryAfter() {
        when(service.importedCandidate(START)).thenReturn(Optional.of(IMPORTED));
        when(service.activateImported(eq(IMPORTED), eq(START), anyString()))
                .thenThrow(new CustomException(ErrorCode.REVISION_CONFLICT));

        scheduler.runOnce();
        clock.advance(Duration.ofMinutes(4));
        scheduler.runOnce();
        verify(service, times(1)).activateImported(eq(IMPORTED), eq(START), anyString());

        clock.advance(Duration.ofMinutes(1));
        scheduler.runOnce();
        verify(service, times(2)).activateImported(eq(IMPORTED), eq(START), anyString());
    }

    @Test
    void anUnavailableSourceIsRetriedOnTheNextRunAndAnyOtherFailureNeverEscapes() {
        when(service.importedCandidate(START)).thenReturn(Optional.of(IMPORTED));
        when(service.activateImported(eq(IMPORTED), eq(START), anyString()))
                .thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE))
                .thenThrow(new IllegalStateException("database"))
                .thenReturn(Optional.empty());

        scheduler.runOnce();
        scheduler.run();
        scheduler.runOnce();

        verify(service, times(3)).activateImported(eq(IMPORTED), eq(START), anyString());
    }

    @Test
    void itRunsOnlyInTheWebApplicationAndOnlyWhenEnabled() {
        // As the application does (SpringApplication registers it): "PT5M" → Duration for the @Value.
        var web = new WebApplicationContextRunner()
                .withInitializer(context -> context.getBeanFactory()
                        .setConversionService(ApplicationConversionService.getSharedInstance()))
                .withBean(AdminGraphVersionService.class, () -> service)
                .withBean(Clock.class, () -> clock)
                .withUserConfiguration(GraphAutoActivationScheduler.class);
        web.run(context -> assertTrue(context.getBeansOfType(GraphAutoActivationScheduler.class).isEmpty(), "off by default"));
        web.withPropertyValues("zoop.graph.auto-activation.enabled=true")
                .run(context -> assertEquals(1, context.getBeansOfType(GraphAutoActivationScheduler.class).size()));
        new ApplicationContextRunner()
                .withInitializer(context -> context.getBeanFactory()
                        .setConversionService(ApplicationConversionService.getSharedInstance()))
                .withBean(AdminGraphVersionService.class, () -> service)
                .withBean(Clock.class, () -> clock)
                .withUserConfiguration(GraphAutoActivationScheduler.class)
                .withPropertyValues("zoop.graph.auto-activation.enabled=true")
                .run(context -> assertTrue(context.getBeansOfType(GraphAutoActivationScheduler.class).isEmpty(),
                        "the operator commands run the same jar without a web server"));
    }

    private static final class MovingClock extends Clock {
        private Instant now;

        MovingClock(Instant now) {
            this.now = now;
        }

        void advance(Duration duration) {
            now = now.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }
}
