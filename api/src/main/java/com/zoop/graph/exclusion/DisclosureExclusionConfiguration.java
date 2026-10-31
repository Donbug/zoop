package com.zoop.graph.exclusion;

import java.nio.file.InvalidPathException;
import java.nio.file.Path;

import com.zoop.ai.handoff.HandoffExposureClient;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.repository.DocumentRegistryRepository;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.support.TransactionOperations;
import org.springframework.web.context.WebApplicationContext;

/**
 * Registers the operator exclusion command only when {@code zoop.disclosure-exclusion.enabled=true}. Unconfigured, the application
 * starts without any of these beans. When enabled, it refuses a web context (an operator run, never next to a server) and an
 * invalid path, naming the setting and never its value. The artifact root is only read ({@code readVerified}: no lock, no session),
 * so the command can run while a graph import holds the store.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.disclosure-exclusion", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(DisclosureExclusionConfiguration.Properties.class)
public class DisclosureExclusionConfiguration {

    /** {@code zoop.disclosure-exclusion.*}, from {@code ZOOP_DISCLOSURE_EXCLUSION_*} and {@code ZOOP_ARTIFACT_ROOT}. */
    @ConfigurationProperties("zoop.disclosure-exclusion")
    public record Properties(@DefaultValue("false") boolean enabled, String request, String result, String artifactRoot) {
        @Override
        public String toString() {
            return "DisclosureExclusionProperties[enabled=" + enabled + "]";
        }
    }

    @Bean
    DisclosureExclusionRunner disclosureExclusionRunner(Properties properties, ApplicationContext context,
            NamedParameterJdbcTemplate jdbc, DocumentRegistryRepository registry, TransactionOperations transaction,
            ObjectProvider<HandoffExposureClient> exposure, com.zoop.graph.importer.GraphHandoffRepository graph,
            com.zoop.graph.publication.JdbcGraphPublicationRepository publications) {
        if (context instanceof WebApplicationContext) {
            throw new IllegalStateException("zoop.disclosure-exclusion.enabled requires spring.main.web-application-type=none");
        }
        ArtifactFileStore store;
        try {
            store = ArtifactFileStore.at(path("artifact-root", properties.artifactRoot()));
        } catch (ArtifactStoreException error) {
            throw new IllegalStateException("zoop.disclosure-exclusion.artifact-root cannot be used as an artifact store");
        }
        return new DisclosureExclusionRunner(path("request", properties.request()), path("result", properties.result()),
                new ExclusionRequestParser(), new DisclosureExclusionService(new JdbcDisclosureExclusionRepository(jdbc), registry,
                        store, transaction, exposure.getIfAvailable(),
                        new com.zoop.graph.publication.GraphPublicationReader(graph, registry, store, publications)));
    }

    private static Path path(String name, String value) {
        try {
            Path path = value == null || value.isBlank() ? null : Path.of(value);
            if (path == null || !path.isAbsolute() || !path.equals(path.normalize())) throw new InvalidPathException("", "");
            return path;
        } catch (InvalidPathException invalid) {
            throw new IllegalStateException("zoop.disclosure-exclusion." + name + " must be a normalized absolute path");
        }
    }
}
