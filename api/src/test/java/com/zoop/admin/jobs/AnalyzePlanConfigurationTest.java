package com.zoop.admin.jobs;

import java.time.Duration;

import com.zoop.admin.jobs.AnalyzePlanState.ServiceBinding;
import com.zoop.ai.AiClientSettings;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.junit.jupiter.api.Assertions.*;

class AnalyzePlanConfigurationTest {
    private static final String TOKEN = "synthetic-test-token-0123456789abcdefghijklmnopqrstuvwxyz";
    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withUserConfiguration(AnalyzePlanConfiguration.class);

    @Test
    void defaultLifecycleIsOffWithoutClientsCredentialsOrDatabase() {
        runner.run(context -> {
            assertNull(context.getStartupFailure());
            assertFalse(context.getBean(AnalyzePlanProperties.class).enabled());
            assertTrue(context.getBeansOfType(AnalyzePlanWorker.class).isEmpty());
            assertTrue(context.getBeansOfType(AnalyzePlanScheduler.class).isEmpty());
            assertTrue(context.getBeansOfType(ServiceBinding.class).isEmpty());
            AnalyzePlanProperties properties = context.getBean(AnalyzePlanProperties.class);
            assertEquals(Duration.ofSeconds(2), properties.pollInterval());
            assertEquals(Duration.ofMinutes(30), properties.attemptDeadline());
            assertEquals(Duration.ofSeconds(150), properties.lease());
            assertEquals(5, properties.maxConsecutiveFailures());
            assertEquals(3, properties.maxRecoveryDispatches());
            assertEquals(16, properties.maxReclaims());
        });
    }

    @Test
    void disabledLifecycleAcceptsTheCentralEmptyPrincipalDefault() {
        runner.withPropertyValues("zoop.analysis.analyze-plan.enabled=false",
                "zoop.analysis.analyze-plan.expected-principal=").run(context -> {
                    assertNull(context.getStartupFailure());
                    assertTrue(context.getBeansOfType(AnalyzePlanWorker.class).isEmpty());
                    assertTrue(context.getBeansOfType(ServiceBinding.class).isEmpty());
                });
    }

    @Test
    void enablingWithoutRealClientBeansFailsStartup() {
        runner.withPropertyValues("zoop.analysis.analyze-plan.enabled=true",
                "zoop.analysis.analyze-plan.expected-principal=app").run(context -> assertNotNull(context.getStartupFailure()));
    }

    @Test
    void enablingWithoutExplicitPrincipalFailsStartup() {
        runner.withPropertyValues("zoop.analysis.analyze-plan.enabled=true")
                .run(context -> assertNotNull(context.getStartupFailure()));
    }

    @Test
    void bindingNormalizesEquivalentEndpointsAndDoesNotIncludeCredentials() {
        AnalyzePlanProperties properties = properties(Duration.ofSeconds(150));
        ServiceBinding first = AnalyzePlanConfiguration.validateBinding(properties,
                settings("https://AI.example:443/mount/", TOKEN, 30),
                settings("https://ai.example/mount", TOKEN, 120), settings("https://ai.example/mount/", TOKEN, 60));
        ServiceBinding rotated = AnalyzePlanConfiguration.validateBinding(properties,
                settings("https://ai.example/mount", TOKEN + "-rotated", 30),
                settings("https://ai.example/mount", TOKEN + "-rotated", 120),
                settings("https://ai.example/mount", TOKEN + "-rotated", 60));
        assertEquals(first, rotated);
        assertEquals(ServiceBinding.of("https://ai.example/mount", "app"), first);
        assertNotEquals(first, ServiceBinding.of("https://ai.example/mount", "other-app"));
        assertFalse(first.toString().contains(TOKEN));
    }

    @Test
    void mismatchedBaseOrLeaseShorterThanLargestRequestAndMarginFailsClosed() {
        var one = settings("https://ai.example", TOKEN, 120);
        var other = settings("https://other.example", TOKEN, 120);
        assertThrows(IllegalArgumentException.class,
                () -> AnalyzePlanConfiguration.validateBinding(properties(Duration.ofSeconds(150)), one, one, other));
        assertThrows(IllegalArgumentException.class,
                () -> AnalyzePlanConfiguration.validateBinding(properties(Duration.ofSeconds(149)), one, one, one));
        assertThrows(IllegalArgumentException.class,
                () -> AnalyzePlanConfiguration.canonicalBase(java.net.URI.create("https://ai.example./")));
    }

    @Test
    void consumerBoundsAreFiniteEvenWhenDisabled() {
        for (String invalid : new String[]{"poll-interval=0s", "attempt-deadline=0s", "lease=0s",
                "max-consecutive-failures=0", "max-recovery-dispatches=0", "max-reclaims=0"}) {
            runner.withPropertyValues("zoop.analysis.analyze-plan." + invalid)
                    .run(context -> assertNotNull(context.getStartupFailure()));
        }
    }

    private static AnalyzePlanProperties properties(Duration lease) {
        return new AnalyzePlanProperties(true, "app", Duration.ofSeconds(2), Duration.ofMinutes(30), lease, 5, 3, 16);
    }

    private static AiClientSettings settings(String base, String token, int seconds) {
        return AiClientSettings.of(base, token, Duration.ofSeconds(3), Duration.ofSeconds(seconds), 65536);
    }
}
