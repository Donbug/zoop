package com.zoop.graph.publication;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import javax.sql.DataSource;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.round.GraphRoundConfigurationException;
import com.zoop.graph.round.GraphRoundProperties;
import com.zoop.graph.round.GraphRoundRepository;
import com.zoop.graph.round.JdbcGraphRoundImportLock;
import com.zoop.graph.round.RoundPreparation;
import com.zoop.graph.version.GraphVersionRepository;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.support.TransactionOperations;

/**
 * The round path's automatic preparation (#55 PR-P3), only with {@code zoop.graph.round.prepare.enabled=true} in the web application
 * that runs the round scheduler (the writer). Startup fails closed, naming the setting, when the rounds are off, when the
 * auto-activation is on (it would move the base the preparation composes on by activating single imports), or when the artifact
 * root the round import writes to or the current rights file is missing. It composes in that same artifact root.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnWebApplication
@ConditionalOnProperty(prefix = "zoop.graph.round.prepare", name = "enabled", havingValue = "true")
public class GraphRoundPrepareConfiguration {

    @Bean
    RoundPreparation graphRoundPreparation(Environment env, GraphHandoffRepository graph, DocumentRegistryRepository registry,
            GraphVersionRepository versions, JdbcGraphPublicationRepository publications, GraphPublicationAuthority authority,
            DocumentReadProperties documentRead, TransactionOperations transaction, DataSource dataSource, NamedParameterJdbcTemplate jdbc,
            GraphRoundRepository rounds, ObjectProvider<GraphRoundProperties> roundProperties, Clock clock) {
        if (!"true".equalsIgnoreCase(env.getProperty("zoop.graph.round.enabled", "false"))) {
            throw new GraphRoundConfigurationException("prepare.enabled", "requires zoop.graph.round.enabled=true");
        }
        if ("true".equalsIgnoreCase(env.getProperty("zoop.graph.auto-activation.enabled", "false"))) {
            throw new GraphRoundConfigurationException("prepare.enabled", "cannot run with zoop.graph.auto-activation.enabled=true");
        }
        if (!"artifact".equalsIgnoreCase(env.getProperty("zoop.graph.snapshot.source", "none"))) {
            throw new GraphRoundConfigurationException("prepare.enabled", "requires zoop.graph.snapshot.source=artifact");
        }
        Path root;
        try {
            root = Path.of(env.getProperty("zoop.graph.snapshot.artifact-root", ""));
        } catch (RuntimeException invalid) {
            root = null;
        }
        if (root == null || !root.isAbsolute() || !root.equals(root.normalize()) || !Files.isDirectory(root)) {
            throw new GraphRoundConfigurationException("prepare.enabled",
                    "requires zoop.graph.snapshot.artifact-root to be an existing normalized absolute directory");
        }
        Path rights;
        try {
            rights = documentRead.ingestionSourcesPath();
        } catch (RuntimeException missing) {
            rights = null;
        }
        if (rights == null) {
            throw new GraphRoundConfigurationException("prepare.enabled", "requires zoop.document-read.ingestion-sources (the current rights)");
        }
        GraphRoundProperties properties = roundProperties.getIfAvailable();
        if (properties == null) {
            throw new GraphRoundConfigurationException("prepare.enabled", "requires zoop.graph.round.enabled=true");
        }
        ArtifactFileStore files = ArtifactFileStore.at(root);
        var reader = new GraphPublicationReader(graph, registry, files, publications);
        var composer = GraphPublicationConfiguration.composer(files, graph, registry, versions, publications, reader, authority, documentRead,
                transaction, clock);
        return new GraphRoundPreparer(rounds, new JdbcGraphPublicationPreparationRepository(jdbc), new JdbcGraphRoundImportLock(dataSource),
                new GraphPublicationPreparer(versions, graph, publications, reader, composer), reader, publications, composer,
                properties.busyRetryAfter(), properties.maxAttemptsPerStage());
    }
}
