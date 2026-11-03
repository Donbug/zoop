package com.zoop.graph.round;

import java.time.Clock;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * The admin round commands in a web process that runs no scheduler (the public web, #55 PR-P4), with
 * {@code zoop.graph.round.commands-enabled=true}. {@code retryGraphRound}·{@code startGraphRound} only change the round row and the
 * writer's scheduler does the work at its next pass, so this process needs the slot calendar (round ids, the current minute) and
 * the writers' heartbeats ({@link TickedGraphRoundStatus}); no scheduler, no bridge. Not with {@code zoop.graph.round.enabled=true}:
 * the scheduler configuration registers its own calendar and status there. The calendar settings must be the writer's.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnWebApplication
@ConditionalOnExpression("'${zoop.graph.round.commands-enabled:false}'.equalsIgnoreCase('true')"
        + " and !'${zoop.graph.round.enabled:false}'.equalsIgnoreCase('true')")
@EnableConfigurationProperties(GraphRoundProperties.class)
public class GraphRoundCommandsConfiguration {

    @Bean
    GraphRoundClock graphRoundCommandsClock(GraphRoundProperties properties) {
        return new GraphRoundClock(properties);
    }

    @Bean
    GraphRoundStatus graphRoundCommandsStatus(GraphRoundTicks ticks, GraphRoundClock graphRoundCommandsClock, Clock clock,
            PlatformTransactionManager transactions) {
        TransactionTemplate own = new TransactionTemplate(transactions);
        // A transaction of its own, so a failed read never aborts the caller's (the overview's, a command's). It borrows a second
        // pooled connection while the caller holds one; admin traffic is a few people, far below the pool size.
        own.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        own.setReadOnly(true);
        return new TickedGraphRoundStatus(ticks, graphRoundCommandsClock, clock, own);
    }
}
