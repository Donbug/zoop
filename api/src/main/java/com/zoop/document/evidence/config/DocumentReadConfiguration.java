package com.zoop.document.evidence.config;

import java.nio.file.Path;
import java.time.Clock;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.evidence.graph.GraphEvidenceReader;
import com.zoop.document.evidence.repository.EvidenceReadRepository;
import com.zoop.document.evidence.service.DocumentReadGrants;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.evidence.service.EvidenceArtifactReader;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.repository.DocumentRegistryRepository;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Wires the public evidence read. Always registered: unconfigured, the application still starts and the read answers 503. The
 * read is one read-only REPEATABLE READ transaction with a statement timeout, so a slow or failing database is a 503 and never
 * an empty success. Building the artifact store only inspects the root; it creates nothing. The graph port is the shared
 * public graph reader: no activation, no second graph path.
 */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(DocumentReadProperties.class)
public class DocumentReadConfiguration {
    /** Seconds a whole evidence read may take inside the database (applied to every statement of the transaction). */
    static final int TRANSACTION_TIMEOUT_SECONDS = 5;

    @Bean
    EvidenceService evidenceService(EvidenceReadRepository evidence, DocumentRegistryRepository registry,
            GraphEvidenceReader graph, DocumentReadProperties properties, Clock clock,
            PlatformTransactionManager transactionManager) {
        Path grants = properties.grantsPath();
        Path sources = properties.ingestionSourcesPath();
        Path root = properties.artifactRootPath();
        ArtifactFileStore store = null;
        if (root != null) {
            try {
                store = ArtifactFileStore.at(root);
            } catch (ArtifactStoreException error) {
                throw new DocumentReadConfigurationException("artifact-root", "cannot be used as an artifact store");
            }
        }
        TransactionTemplate transaction = new TransactionTemplate(transactionManager);
        transaction.setReadOnly(true);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        transaction.setTimeout(TRANSACTION_TIMEOUT_SECONDS);
        return new EvidenceService(evidence, registry, new DocumentReadGrants(grants), new DocumentReadSources(sources), graph,
                new EvidenceArtifactReader(store), clock, transaction);
    }
}
