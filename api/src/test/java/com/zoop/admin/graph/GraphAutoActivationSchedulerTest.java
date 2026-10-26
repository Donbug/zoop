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
    /** One round (lookback) before the start: an import of the current round from just before a restart still counts. */
    private static final Instant SINCE = START.minus(Duration.ofMinutes(30));
    private static final GraphVersionRecord IMPORTED = new GraphVersionRecord(
            "gv-2", 7, "snapshot", "artifact-2", "artifact://gv-2.json", "a".repeat(64), false);
    private static final GraphVersionRecord NEWER = new GraphVersionRecord(
            "gv-3", 8, "snapshot", "artifact-3", "artifact://gv-3.json", "b".repeat(64), false);

    private final AdminGraphVersionService service = mock(AdminGraphVersionService.class);
    private final MovingClock clock = new MovingClock(START);
    private final GraphAutoActivationScheduler scheduler = new GraphAutoActivationScheduler(service, clock,
            Duration.ofSeconds(15), Duration.ofMinutes(30), Duration.ofMinutes(5), Duration.ofMinutes(1));

    @Test
    void versionsFromOneLookbackBeforeTheStartAreCandidatesAndNothingIsTriedWithoutOne() {
        when(service.importedCandidate(SINCE)).thenReturn(Optional.empty());
        clock.advance(Duration.ofMinutes(1));

        scheduler.runOnce();

        verify(service).importedCandidate(SINCE);
        verify(service, never()).activateImported(any(), any(), anyString());
    }

    @Test
    void theCandidateIsActivatedWithTheSameWindowStart() {
        when(service.importedCandidate(SINCE)).thenReturn(Optional.of(IMPORTED));
        when(service.activateImported(eq(IMPORTED), eq(SINCE), anyString()))
                .thenReturn(Optional.of(new Activation("gv-1", true, START.plusSeconds(15))));

        scheduler.runOnce();

        verify(service).activateImported(eq(IMPORTED), eq(SINCE), anyString());
    }

    @Test
    void aRefusedVersionIsRetriedOnlyAfterRetryAfter() {
        when(service.importedCandidate(SINCE)).thenReturn(Optional.of(IMPORTED));
        when(service.activateImported(eq(IMPORTED), eq(SINCE), anyString()))
                .thenThrow(new CustomException(ErrorCode.REVISION_CONFLICT));

        scheduler.runOnce();
        clock.advance(Duration.ofMinutes(4));
        scheduler.runOnce();
        verify(service, times(1)).activateImported(eq(IMPORTED), eq(SINCE), anyString());

        clock.advance(Duration.ofMinutes(1));
        scheduler.runOnce();
        verify(service, times(2)).activateImported(eq(IMPORTED), eq(SINCE), anyString());
    }

    @Test
    void anUnavailableSourceOrAnyOtherFailureWaitsUnavailableRetryAfterAndNeverEscapes() {
        when(service.importedCandidate(SINCE)).thenReturn(Optional.of(IMPORTED));
        when(service.activateImported(eq(IMPORTED), eq(SINCE), anyString()))
                .thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE))
                .thenThrow(new IllegalStateException("database"))
                .thenReturn(Optional.empty());

        scheduler.runOnce();
        clock.advance(Duration.ofSeconds(15));
        scheduler.runOnce();
        verify(service, times(1)).activateImported(eq(IMPORTED), eq(SINCE), anyString());
        clock.advance(Duration.ofMinutes(1));
        scheduler.runOnce();
        verify(service, times(2)).activateImported(eq(IMPORTED), eq(SINCE), anyString());
        clock.advance(Duration.ofMinutes(1));
        scheduler.runOnce();
        verify(service, times(3)).activateImported(eq(IMPORTED), eq(SINCE), anyString());

        when(service.importedCandidate(SINCE)).thenThrow(new IllegalStateException("database"));
        scheduler.runOnce();
    }

    @Test
    @SuppressWarnings("unchecked") // consecutive Optional answers: a generic varargs call
    void aNewerImportIsTriedAtOnceWhileAnOlderOneWaitsAndASuccessForgetsEveryWait() {
        when(service.importedCandidate(SINCE)).thenReturn(Optional.of(IMPORTED), Optional.of(NEWER), Optional.of(IMPORTED));
        when(service.activateImported(eq(IMPORTED), eq(SINCE), anyString()))
                .thenThrow(new CustomException(ErrorCode.REVISION_CONFLICT))
                .thenReturn(Optional.empty());
        when(service.activateImported(eq(NEWER), eq(SINCE), anyString()))
                .thenReturn(Optional.of(new Activation("gv-1", true, START)));

        scheduler.runOnce();
        scheduler.runOnce();
        verify(service).activateImported(eq(NEWER), eq(SINCE), anyString());

        scheduler.runOnce();
        verify(service, times(2)).activateImported(eq(IMPORTED), eq(SINCE), anyString());
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
