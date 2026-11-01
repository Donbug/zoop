package com.zoop.graph.delivery.seal;

import java.io.IOException;
import java.nio.file.Path;
import java.time.Clock;
import javax.sql.DataSource;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliverySchemaGuard;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore;
import com.zoop.graph.importer.GraphHandoffImporter;
import com.zoop.graph.importer.GraphHandoffImportSettings;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.importer.HandoffSourceContexts;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.JdbcGraphPublicationRepository;
import org.springframework.beans.factory.ObjectProvider;
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
@ConditionalOnProperty(prefix = "zoop.graph-delivery.seal", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(GraphDeliverySealProperties.class)
public class GraphDeliverySealConfiguration {
    @Bean
    static BeanFactoryPostProcessor graphDeliverySealStartupGuard(Environment environment) {
        return factory -> {
            GraphDeliverySchemaGuard.requireNoMigration(environment);
            for (String property : new String[] {"zoop.graph-delivery.install.enabled", "zoop.document-import.enabled",
                    "zoop.document-analysis.enabled", "zoop.disclosure-exclusion.enabled", "zoop.graph.auto-activation.enabled",
                    "zoop.legacy-real-import.enabled", "zoop.document-bindings.enabled", "zoop.briefing.replay.import-enabled",
                    "zoop.graph-publication-compose.enabled"}) {
                if (environment.getProperty(property, Boolean.class, false)) throw new GraphDeliveryException("configuration_invalid");
            }
            if ("fixture".equalsIgnoreCase(environment.getProperty("zoop.graph.snapshot.source"))) {
                throw new GraphDeliveryException("configuration_invalid");
            }
            boolean seal = "seal".equals(environment.getProperty("zoop.graph-delivery.seal.command", "seal"));
            if (seal != environment.getProperty("zoop.graph-handoff-import.enabled", Boolean.class, false)) {
                throw new GraphDeliveryException("configuration_invalid");
            }
            if (!seal && environment.getProperty("zoop.ai.handoff-read-client.enabled", Boolean.class, false)) {
                throw new GraphDeliveryException("configuration_invalid");
            }
        };
    }

    @Bean
    JdbcGraphDeliveryStore sealGraphDeliveryStore(JdbcTemplate jdbc) { return new JdbcGraphDeliveryStore(jdbc); }

    @Bean
    @ConditionalOnProperty(prefix = "zoop.graph-delivery.seal", name = "command", havingValue = "seal", matchIfMissing = true)
    GraphDeliverySealer graphDeliverySealer(ArtifactFileStore files, DocumentRegistryRepository registry,
            GraphVersionRepository versions, GraphHandoffRepository graph, JdbcGraphDeliveryStore deliveries,
            GraphHandoffImporter importer, PlatformTransactionManager manager, Clock clock, GraphHandoffImportSettings imports,
            GraphDeliverySealProperties settings) {
        try {
            Path parent = settings.resultPath().getParent().toRealPath();
            for (Path forbidden : new Path[] {imports.artifactRoot(), imports.handoffState(), imports.relationState(),
                    imports.extractionState(), imports.ingestionState()}) {
                if (forbidden != null && parent.startsWith(forbidden.toRealPath())) throw new GraphDeliveryException("configuration_invalid");
            }
            if (imports.sourceContexts() != null) {
                for (Path forbidden : HandoffSourceContexts.read(imports.sourceContexts(), imports.sourceContextsSha256()).roots()) {
                    if (parent.startsWith(forbidden.toRealPath())) throw new GraphDeliveryException("configuration_invalid");
                }
            }
        } catch (IOException invalid) {
            throw new GraphDeliveryException("configuration_invalid");
        }
        TransactionTemplate transaction = new TransactionTemplate(manager);
        transaction.setTimeout(300);
        return new GraphDeliverySealer(files, registry, versions, graph, deliveries, importer, transaction, clock, null, null);
    }

    @Bean
    @ConditionalOnProperty(prefix = "zoop.graph-delivery.seal", name = "command", havingValue = "seal-publication")
    GraphDeliverySealer publicationGraphDeliverySealer(DocumentRegistryRepository registry, GraphVersionRepository versions,
            GraphHandoffRepository graph, JdbcGraphDeliveryStore deliveries, PlatformTransactionManager manager, Clock clock,
            GraphDeliverySealProperties settings, JdbcTemplate jdbc, Environment environment) {
        settings.validate();
        ArtifactFileStore files = ArtifactFileStore.at(settings.artifactRootPath());
        TransactionTemplate transaction = new TransactionTemplate(manager);
        transaction.setTimeout(300);
        var reader = new GraphPublicationReader(graph, registry, files,
                new JdbcGraphPublicationRepository(new org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate(jdbc)));
        return new GraphDeliverySealer(files, registry, versions, graph, deliveries, null, transaction, clock, reader,
                environment.getProperty("zoop.document-read.ingestion-sources"));
    }

    @Bean
    GraphDeliverySealRunner graphDeliverySealRunner(GraphDeliverySealProperties settings,
            ObjectProvider<GraphDeliverySealer> sealer, ObjectProvider<GraphHandoffImportSettings> imports,
            JdbcGraphDeliveryStore deliveries, GraphVersionRepository versions, DataSource dataSource, ApplicationContext context) {
        if (context instanceof WebApplicationContext) throw new GraphDeliveryException("configuration_invalid");
        settings.validate();
        return new GraphDeliverySealRunner(settings, sealer, imports, deliveries, versions, dataSource, context.getEnvironment());
    }
}
