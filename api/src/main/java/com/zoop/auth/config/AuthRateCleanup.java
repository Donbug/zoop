package com.zoop.auth.config;

import java.time.Clock;
import java.time.Duration;

import com.zoop.auth.repository.AuthRateEventStore;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
@EnableScheduling
public class AuthRateCleanup {
    private final AuthRateEventStore store;
    private final Clock clock;

    public AuthRateCleanup(AuthRateEventStore store, Clock clock) {
        this.store = store;
        this.clock = clock;
    }

    @Scheduled(fixedDelayString = "PT1H", initialDelayString = "PT1H")
    @Transactional
    public void purgeExpiredEvents() {
        store.purgeBefore(clock.instant().minus(Duration.ofHours(1)));
    }
}
