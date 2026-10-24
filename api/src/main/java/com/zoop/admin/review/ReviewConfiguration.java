package com.zoop.admin.review;

import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ReviewConfiguration {
    /** Until the AI relation review client exists, decisions fail closed instead of being recorded only in the app. */
    @Bean
    @ConditionalOnMissingBean(RelationReviewClient.class)
    RelationReviewClient unconfiguredRelationReviewClient() {
        return new RelationReviewClient.Unconfigured();
    }
}
