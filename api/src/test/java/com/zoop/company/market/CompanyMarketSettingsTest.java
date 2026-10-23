package com.zoop.company.market;

import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class CompanyMarketSettingsTest {
    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withUserConfiguration(MarketDataConfiguration.class);

    @Test
    void usesFiveMinuteQuoteCacheByDefault() {
        runner.run(context -> {
            assertNull(context.getStartupFailure());
            assertEquals(Duration.ofMinutes(5), context.getBean(CompanyMarketSettings.class).quoteCacheTtl());
        });
    }

    @Test
    void bindsMarketCacheSettingsThroughSpringConfigurationProperties() {
        runner.withPropertyValues(
                "zoop.market.quote-cache-ttl=15s",
                "zoop.market.metrics-cache-ttl=20m",
                "zoop.market.price-cache-ttl=45s",
                "zoop.market.cache-max-entries=128",
                "zoop.market.provider-max-concurrent-requests=3")
                .run(context -> {
                    assertNull(context.getStartupFailure());
                    var settings = context.getBean(CompanyMarketSettings.class);
                    assertEquals(Duration.ofSeconds(15), settings.quoteCacheTtl());
                    assertEquals(Duration.ofMinutes(20), settings.metricsCacheTtl());
                    assertEquals(Duration.ofSeconds(45), settings.priceCacheTtl());
                    assertEquals(128, settings.cacheMaxEntries());
                    assertEquals(3, settings.providerMaxConcurrentRequests());
                });
    }
}
