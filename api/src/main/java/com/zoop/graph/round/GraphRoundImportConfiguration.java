package com.zoop.graph.round;

import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.time.Clock;

import javax.sql.DataSource;

import com.zoop.ai.handoff.HandoffReadClient;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.ProcessIngestionExporter;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.importer.GraphHandoffImporter;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.importer.HttpHandoffSource;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.transaction.support.TransactionOperations;

/**
 * The round's import bridge inside the web application, only with {@code zoop.graph.round.enabled=true}. It is the web
 * counterpart of {@code GraphHandoffImportConfiguration} (the operator command, non-web only): the same importer, but the handoff
 * comes from ai/service's read-only handoff HTTP and the result goes to the round row instead of a result file. Startup fails
 * closed, naming the setting, when:
 * <ul>
 * <li>the public snapshot source is not {@code artifact}: the versions the bridge stages must be readable by this same process
 *     (the auto-activation loads them), so the bridge writes into {@code zoop.graph.snapshot.artifact-root} and nowhere else;
 *     {@code fixture} is refused because its seeder activates versions;</li>
 * <li>{@code zoop.ai.handoff-read-client} is not enabled: there is no other way to read a handoff here;</li>
 * <li>{@code import-source=cli} and the S2-1 CLI, ledger directory or source registry is missing: the observation re-check still
 *     runs the installed {@code zoop-ai-ingest export --require-store} (local, single-instance operation); {@code http} is
 *     refused until the AI side's observation export route exists (#387 ③).</li>
 * </ul>
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnWebApplication
@ConditionalOnProperty(prefix = "zoop.graph.round", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(GraphRoundProperties.class)
public class GraphRoundImportConfiguration {

    @Bean
    GraphRoundImportBridge graphRoundImportBridge(GraphRoundProperties properties, Environment environment,
            ObjectProvider<HandoffReadClient> handoffReads, DocumentRegistryRepository registry, GraphHandoffRepository graph,
            GraphRoundRepository rounds, TransactionOperations transaction, DataSource dataSource, Clock clock) {
        Path root = artifactRoot(environment);
        HandoffReadClient client = handoffReads.getIfAvailable();
        if (client == null) {
            throw new GraphRoundConfigurationException("enabled", "requires zoop.ai.handoff-read-client.enabled=true");
        }
        ProcessIngestionExporter ingestion = ingestionExporter(properties);
        ArtifactFileStore store;
        try {
            store = ArtifactFileStore.at(root);
        } catch (ArtifactStoreException error) {
            throw new GraphRoundConfigurationException("enabled",
                    "requires a usable zoop.graph.snapshot.artifact-root (the bridge writes the versions it stages there)");
        }
        GraphHandoffImporter importer = new GraphHandoffImporter(new HttpHandoffSource(client), ingestion,
                new IngestionExportParser(), store, registry, graph, transaction, clock);
        return new GraphRoundImportBridge(importer, rounds, new JdbcGraphRoundImportLock(dataSource), properties, clock);
    }

    private static Path artifactRoot(Environment environment) {
        String source = environment.getProperty("zoop.graph.snapshot.source", "none");
        if (!"artifact".equalsIgnoreCase(source)) {
            throw new GraphRoundConfigurationException("enabled",
                    "requires zoop.graph.snapshot.source=artifact (the fixture seeder activates versions; none cannot read them)");
        }
        String value = environment.getProperty("zoop.graph.snapshot.artifact-root", "");
        try {
            Path root = Path.of(value);
            if (value.isBlank() || !root.isAbsolute() || !root.equals(root.normalize()) || !Files.isDirectory(root)) {
                throw new GraphRoundConfigurationException("enabled",
                        "requires zoop.graph.snapshot.artifact-root to be an existing normalized absolute directory");
            }
            return root;
        } catch (InvalidPathException error) {
            throw new GraphRoundConfigurationException("enabled", "requires a valid zoop.graph.snapshot.artifact-root");
        }
    }

    private static ProcessIngestionExporter ingestionExporter(GraphRoundProperties properties) {
        if ("http".equalsIgnoreCase(properties.importSource())) {
            throw new GraphRoundConfigurationException("import-source",
                    "http is not available yet (the AI side's observation export route is pending); use cli");
        }
        if (!"cli".equalsIgnoreCase(properties.importSource())) {
            throw new GraphRoundConfigurationException("import-source", "must be cli or http");
        }
        Path cli = absolute("ingestion-cli", properties.ingestionCli());
        Path state = absolute("ingestion-state-dir", properties.ingestionStateDir());
        Path sources = absolute("ingestion-sources", properties.ingestionSources());
        require(Files.isRegularFile(cli) && Files.isExecutable(cli), "ingestion-cli", "must be an existing executable file");
        require(Files.isDirectory(state), "ingestion-state-dir", "must be an existing directory");
        require(Files.isRegularFile(sources), "ingestion-sources", "must be an existing file");
        return ProcessIngestionExporter.forPaths(cli, state, sources);
    }

    private static Path absolute(String setting, String value) {
        if (value == null || value.isBlank()) {
            throw new GraphRoundConfigurationException(setting, "is required with import-source=cli");
        }
        try {
            Path path = Path.of(value);
            require(path.isAbsolute() && path.equals(path.normalize()), setting, "must be a normalized absolute path");
            return path;
        } catch (InvalidPathException error) {
            throw new GraphRoundConfigurationException(setting, "must be a valid path");
        }
    }

    private static void require(boolean condition, String setting, String rule) {
        if (!condition) throw new GraphRoundConfigurationException(setting, rule);
    }
}
