package com.zoop.document.importer;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.service.DocumentRegistrationService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.context.WebApplicationContext;

/**
 * Registers the operator document import only when {@code zoop.document-import.enabled=true}. Unconfigured, the application
 * starts without any import setting and none of these beans exists. When enabled, an invalid setting fails startup
 * (closed) with a message that names the setting, not its value, and so does a web application context: the import is an
 * operator run (start it with {@code --spring.main.web-application-type=none}), never something to run next to a server.
 * The failure happens while beans are created, before a web server would start listening.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.document-import", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(DocumentImportProperties.class)
public class DocumentImportConfiguration {

    @Bean
    DocumentImportSettings documentImportSettings(DocumentImportProperties properties, ApplicationContext context) {
        if (context instanceof WebApplicationContext) {
            throw new DocumentImportConfigurationException("enabled",
                    "requires spring.main.web-application-type=none (no web server may run during an import)");
        }
        if ("true".equalsIgnoreCase(context.getEnvironment().getProperty("zoop.document-analysis.enabled"))) {
            throw new DocumentImportConfigurationException("enabled",
                    "cannot run together with zoop.document-analysis.enabled (each run holds the artifact store lock)");
        }
        return properties.toSettings();
    }

    @Bean
    ArtifactFileStore documentImportArtifactStore(DocumentImportSettings settings) {
        try {
            return ArtifactFileStore.at(settings.artifactRoot());
        } catch (ArtifactStoreException error) {
            throw new DocumentImportConfigurationException("artifact-root", "cannot be used as an artifact store");
        }
    }

    @Bean
    DocumentImportRunner documentImportRunner(DocumentImportSettings settings, ArtifactFileStore store,
            DocumentRegistrationService registration) {
        return new DocumentImportRunner(settings, new ImportRequestParser(), new DocumentImporter(
                ProcessIngestionExporter.forSettings(settings), new IngestionExportParser(), store, registration));
    }
}
