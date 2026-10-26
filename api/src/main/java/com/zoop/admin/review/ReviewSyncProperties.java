package com.zoop.admin.review;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** The review-target sync round: how often it runs and how many units each of its two passes reads. */
@ConfigurationProperties("zoop.analysis.review-sync")
public record ReviewSyncProperties(
        @DefaultValue("60s") Duration interval,
        @DefaultValue("20") int batch) {

    public ReviewSyncProperties {
        if (interval == null || interval.compareTo(Duration.ofSeconds(1)) < 0 || interval.compareTo(Duration.ofHours(1)) > 0) {
            throw new IllegalArgumentException("zoop.analysis.review-sync.interval is outside its finite bounds");
        }
        if (batch < 1 || batch > 500) {
            throw new IllegalArgumentException("zoop.analysis.review-sync.batch is outside its finite bounds");
        }
    }
}
