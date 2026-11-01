package com.zoop.graph.round;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.time.Clock;
import java.util.UUID;

import com.zoop.admin.jobs.AnalysisJobRoundQueue;
import com.zoop.admin.jobs.AnalysisJobService;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository;
import com.zoop.ai.config.AiRoundClientProperties;
import com.zoop.ai.round.RoundHandoffClient;
import com.zoop.ai.round.RoundRunClient;
import com.zoop.document.bindings.DocumentBindingsExporter;
import com.zoop.document.bindings.DocumentBindingsScope;
import com.zoop.document.bindings.JdbcDocumentBindingsRepository;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import tools.jackson.databind.ObjectMapper;

/**
 * The round scheduler (#55 A-6), only with {@code zoop.graph.round.enabled=true} in the web application, next to the import
 * bridge of {@link GraphRoundImportConfiguration}. Startup fails closed, naming the setting, when a party the stages call is
 * missing: the AI round client ({@code zoop.ai.round-client}, R1·R2·R5·R6) or the analyze_plan queue
 * ({@code zoop.analysis.analyze-plan.enabled=true}, R3·R4). The handoff-read client and the artifact source are the bridge's
 * requirements and fail there.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnWebApplication
@ConditionalOnProperty(prefix = "zoop.graph.round", name = "enabled", havingValue = "true")
public class GraphRoundSchedulerConfiguration {

    @Bean
    GraphRoundClock graphRoundClock(GraphRoundProperties properties) {
        return new GraphRoundClock(properties);
    }

    @Bean
    RoundAnalysisQueue graphRoundAnalysisQueue(AnalysisJobService jobs, JdbcAnalysisJobRepository repository, ObjectMapper mapper,
            Environment environment) {
        if (!"true".equalsIgnoreCase(environment.getProperty("zoop.analysis.analyze-plan.enabled", "false"))) {
            throw new GraphRoundConfigurationException("enabled", "requires zoop.analysis.analyze-plan.enabled=true (R3 queues the plan)");
        }
        return new AnalysisJobRoundQueue(jobs, repository, mapper);
    }

    /** Every registered version (A-10, #407 app change 6): the freeze's window is not known before the freeze. */
    @Bean
    RoundBindingsSource graphRoundBindings(NamedParameterJdbcTemplate jdbc) {
        DocumentBindingsExporter exporter = new DocumentBindingsExporter(new JdbcDocumentBindingsRepository(jdbc));
        return () -> exporter.export(DocumentBindingsScope.ALL, null).bytes();
    }

    @Bean
    GraphRoundWorker graphRoundWorker(GraphRoundRepository rounds, GraphRoundClock calendar, ObjectProvider<RoundRunClient> runs,
            ObjectProvider<RoundHandoffClient> handoffs, RoundAnalysisQueue analysis, RoundBindingsSource bindings,
            GraphRoundImportBridge bridge, GraphRoundProperties properties, ObjectProvider<AiRoundClientProperties> settings, Clock clock) {
        RoundRunClient runClient = runs.getIfAvailable();
        RoundHandoffClient handoffClient = handoffs.getIfAvailable();
        AiRoundClientProperties clientProperties = settings.getIfAvailable();
        if (runClient == null || handoffClient == null || clientProperties == null) {
            throw new GraphRoundConfigurationException("enabled", "requires zoop.ai.round-client.enabled=true (R1·R2·R5·R6 call the AI side)");
        }
        RoundServiceBinding binding = RoundServiceBinding.of(clientProperties.toSettings(), clientProperties.expectedPrincipal());
        return new GraphRoundWorker(rounds, calendar, runClient, handoffClient, analysis, bindings, bridge, properties,
                binding, clock, owner());
    }

    @Bean
    GraphRoundScheduler graphRoundScheduler(GraphRoundWorker worker, GraphRoundClock calendar, Clock clock,
            GraphRoundProperties properties) {
        return new GraphRoundScheduler(worker, calendar, clock, properties.interval());
    }

    /** The lease owner of this instance: host name plus a per-start suffix, so two instances or a restart never share one. */
    static String owner() {
        String host;
        try {
            host = InetAddress.getLocalHost().getHostName();
        } catch (UnknownHostException | RuntimeException unknown) {
            host = "instance";
        }
        String safe = host.replaceAll("[^A-Za-z0-9.-]", "-");
        return (safe.length() > 40 ? safe.substring(0, 40) : safe) + "-" + UUID.randomUUID().toString().substring(0, 8);
    }
}
