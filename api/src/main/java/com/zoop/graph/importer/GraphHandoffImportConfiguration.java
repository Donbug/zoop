package com.zoop.graph.importer;

import java.time.Clock;

import com.zoop.ai.handoff.HandoffReadClient;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.ProcessIngestionExporter;
import com.zoop.document.repository.DocumentRegistryRepository;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.transaction.support.TransactionOperations;
import org.springframework.web.context.WebApplicationContext;

/**
 * Registers the operator graph handoff import only when {@code zoop.graph-handoff-import.enabled=true}. Unconfigured, the
 * application starts without any import setting and none of these beans exists. When enabled, an invalid setting fails startup
 * (closed) with a message that names the setting, not its value, and so does any of these, because each would make the run
 * unsafe or ambiguous:
 * <ul>
 * <li>a web application context: the import is an operator run (start it with {@code --spring.main.web-application-type=none}),
 *     never something to run next to a server;</li>
 * <li>a document import or analysis enabled in the same process: every run holds the artifact store lock for its whole life;</li>
 * <li>{@code zoop.graph.snapshot.source=fixture}: the fixture seeder registers AND ACTIVATES versions at startup, which a staging
 *     run must never do;</li>
 * <li>{@code handoff-source=http} without {@code zoop.ai.handoff-read-client.enabled=true}: the import would have no handoff
 *     source at all.</li>
 * </ul>
 * The failure happens while beans are created, before a web server would start listening.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.graph-handoff-import", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(GraphHandoffImportProperties.class)
public class GraphHandoffImportConfiguration {

    @Bean
    GraphHandoffImportSettings graphHandoffImportSettings(GraphHandoffImportProperties properties, ApplicationContext context) {
        if (context instanceof WebApplicationContext) {
            throw new GraphHandoffImportConfigurationException("enabled",
                    "requires spring.main.web-application-type=none (no web server may run during an import)");
        }
        for (String other : new String[] {"zoop.document-import.enabled", "zoop.document-analysis.enabled"}) {
            if ("true".equalsIgnoreCase(context.getEnvironment().getProperty(other))) {
                throw new GraphHandoffImportConfigurationException("enabled",
                        "cannot run together with " + other + " (each run holds the artifact store lock)");
            }
        }
        if ("fixture".equalsIgnoreCase(context.getEnvironment().getProperty("zoop.graph.snapshot.source"))) {
            throw new GraphHandoffImportConfigurationException("enabled",
                    "cannot run together with zoop.graph.snapshot.source=fixture (the fixture seeder activates versions)");
        }
        return properties.toSettings();
    }

    @Bean
    ArtifactFileStore graphHandoffImportArtifactStore(GraphHandoffImportSettings settings) {
        try {
            return ArtifactFileStore.at(settings.artifactRoot());
        } catch (ArtifactStoreException error) {
            throw new GraphHandoffImportConfigurationException("artifact-root", "cannot be used as an artifact store");
        }
    }

    @Bean
    GraphHandoffRunner graphHandoffRunner(GraphHandoffImportSettings settings, ArtifactFileStore store,
            DocumentRegistryRepository registry, GraphHandoffRepository graph, TransactionOperations transaction, Clock clock,
            ObjectProvider<HandoffReadClient> handoffReads) {
        return new GraphHandoffRunner(settings, new GraphHandoffRequestParser(), new GraphHandoffImporter(
                handoffSource(settings, handoffReads),
                ProcessIngestionExporter.forPaths(settings.ingestionCli(), settings.ingestionState(),
                        settings.ingestionSources()),
                new IngestionExportParser(), store, registry, graph, transaction, clock));
    }

    /**
     * The CLI export, or the read-only handoff HTTP client that {@code zoop.ai.handoff-read-client} registers. {@code http} needs
     * the client; {@code cli} ignores one that is enabled (the same environment serves the web application's round bridge, which
     * needs it), unlike the CLI-only settings, which belong to this import alone.
     */
    static HandoffSource handoffSource(GraphHandoffImportSettings settings, ObjectProvider<HandoffReadClient> handoffReads) {
        HandoffReadClient client = handoffReads.getIfAvailable();
        if (settings.handoffSource() == GraphHandoffImportSettings.HandoffSourceKind.HTTP) {
            if (client == null) {
                throw new GraphHandoffImportConfigurationException("handoff-source",
                        "http requires zoop.ai.handoff-read-client.enabled=true");
            }
            return new HttpHandoffSource(client);
        }
        return new CliHandoffSource(ProcessHandoffExporter.forSettings(settings));
    }
}
