package com.zoop.document.analysis;

import java.time.Clock;

import com.zoop.ai.AiAnalysisClient;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.analysis.repository.DocumentAnalysisRepository;
import com.zoop.document.analysis.service.DocumentAnalysisService;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.ProcessIngestionExporter;
import com.zoop.document.repository.DocumentRegistryRepository;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.context.WebApplicationContext;

/**
 * Registers the operator document analysis only when {@code zoop.document-analysis.enabled=true}. Unconfigured, the application
 * starts without any analysis setting and none of these beans exists. When enabled, an invalid setting fails startup (closed)
 * with a message that names the setting, not its value, and so does a web application context (the analysis is an operator run:
 * start it with {@code --spring.main.web-application-type=none}, never next to a server), a document import enabled in the same
 * process (both hold the artifact store lock for a whole run) and a missing AI client ({@code zoop.ai.client.enabled=true}).
 * The failure happens while beans are created, before a web server would start listening.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.document-analysis", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(DocumentAnalysisProperties.class)
public class DocumentAnalysisConfiguration {

    @Bean
    DocumentAnalysisSettings documentAnalysisSettings(DocumentAnalysisProperties properties, ApplicationContext context) {
        if (context instanceof WebApplicationContext) {
            throw new DocumentAnalysisConfigurationException("enabled",
                    "requires spring.main.web-application-type=none (no web server may run during an analysis)");
        }
        if ("true".equalsIgnoreCase(context.getEnvironment().getProperty("zoop.document-import.enabled"))) {
            throw new DocumentAnalysisConfigurationException("enabled",
                    "cannot run together with zoop.document-import.enabled (each run holds the artifact store lock)");
        }
        return properties.toSettings();
    }

    @Bean
    ArtifactFileStore documentAnalysisArtifactStore(DocumentAnalysisSettings settings) {
        try {
            return ArtifactFileStore.at(settings.artifactRoot());
        } catch (ArtifactStoreException error) {
            throw new DocumentAnalysisConfigurationException("artifact-root", "cannot be used as an artifact store");
        }
    }

    @Bean
    DocumentAnalysisRunner documentAnalysisRunner(DocumentAnalysisSettings settings, ArtifactFileStore store,
            ObjectProvider<AiAnalysisClient> client, DocumentRegistryRepository registry, DocumentAnalysisRepository analyses,
            DocumentAnalysisService service, Clock clock) {
        AiAnalysisClient aiClient = client.getIfAvailable();
        if (aiClient == null) {
            throw new DocumentAnalysisConfigurationException("enabled",
                    "requires the S1 AI client (zoop.ai.client.enabled=true and its settings)");
        }
        return new DocumentAnalysisRunner(settings, new AnalysisRequestParser(), new DocumentAnalyzer(settings.grants(),
                ProcessIngestionExporter.forPaths(settings.ingestionCli(), settings.ingestionState(),
                        settings.ingestionSources()),
                new IngestionExportParser(), store, registry, analyses, service, aiClient, clock));
    }
}
