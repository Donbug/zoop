package com.zoop.admin.review;

import com.zoop.ai.relation.RelationClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ReviewConfiguration {
    /**
     * The AI relation review routes over the S3 client when {@code zoop.ai.relation-client.enabled=true}; otherwise decisions fail
     * closed ({@link RelationReviewClient.Unconfigured}) instead of being recorded only in the app.
     */
    @Bean
    @ConditionalOnMissingBean(RelationReviewClient.class)
    RelationReviewClient relationReviewClient(ObjectProvider<RelationClient> relations) {
        RelationClient client = relations.getIfAvailable();
        return client == null ? new RelationReviewClient.Unconfigured() : new AiRelationReviewClient(client);
    }
}
