package com.zoop.graph.delivery.install;

import java.time.Clock;
import javax.sql.DataSource;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliverySchemaGuard;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.JdbcGraphPublicationRepository;
import org.springframework.beans.factory.config.BeanFactoryPostProcessor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.context.WebApplicationContext;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.graph-delivery.install", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(GraphDeliveryInstallProperties.class)
public class GraphDeliveryInstallConfiguration {
    @Bean
    static BeanFactoryPostProcessor graphDeliveryInstallMigrationGuard(Environment environment) {
        return factory -> {
            GraphDeliverySchemaGuard.requireNoMigration(environment);
            for (String other : new String[] {"zoop.document-import.enabled", "zoop.document-analysis.enabled",
                    "zoop.graph-handoff-import.enabled", "zoop.graph-delivery.seal.enabled", "zoop.disclosure-exclusion.enabled",
                    "zoop.graph.auto-activation.enabled", "zoop.legacy-real-import.enabled", "zoop.document-bindings.enabled",
                    "zoop.briefing.replay.import-enabled", "zoop.ai.handoff-read-client.enabled",
                    "zoop.graph-publication-compose.enabled"}) {
                if (environment.getProperty(other, Boolean.class, false)) throw new GraphDeliveryException("configuration_invalid");
            }
            if ("fixture".equalsIgnoreCase(environment.getProperty("zoop.graph.snapshot.source"))) {
                throw new GraphDeliveryException("configuration_invalid");
            }
        };
    }

    @Bean
    GraphDeliveryInstallSettings graphDeliveryInstallSettings(GraphDeliveryInstallProperties properties,
            ApplicationContext context) {
        if (context instanceof WebApplicationContext) throw new GraphDeliveryException("configuration_invalid");
        return GraphDeliveryInstallSettings.of(properties, context.getEnvironment().getProperty("zoop.document-read.ingestion-sources"));
    }

    @Bean
    GraphDeliveryInstallRunner graphDeliveryInstallRunner(GraphDeliveryInstallSettings settings, JdbcTemplate jdbc,
            DocumentRegistryRepository registry, GraphVersionRepository versions, GraphHandoffRepository graph,
            PlatformTransactionManager manager, Clock clock, DataSource dataSource, Environment environment) {
        TransactionTemplate transaction = new TransactionTemplate(manager);
        transaction.setTimeout(300);
        var deliveries = new JdbcGraphDeliveryStore(jdbc);
        var reader = new GraphPublicationReader(graph, registry, deliveries::readContent,
                new JdbcGraphPublicationRepository(new org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate(jdbc)));
        var installer = new GraphDeliveryInstaller(ArtifactFileStore.at(settings.artifactRoot()),
                deliveries, registry, versions, graph, transaction, clock, reader);
        return new GraphDeliveryInstallRunner(settings, installer, dataSource, environment);
    }
}
