package com.zoop.graph.publication;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFileAttributes;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.util.Set;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.read.DisclosureExclusionReader;
import com.zoop.graph.version.GraphVersionRepository;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.transaction.support.TransactionOperations;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.node.ObjectNode;

@Configuration(proxyBeanMethods = false)
public class GraphPublicationConfiguration {
    @Bean
    GraphPublicationReader graphPublicationReader(GraphHandoffRepository graph, DocumentRegistryRepository registry,
            JdbcGraphPublicationRepository publications, DocumentReadProperties properties) {
        Path root = properties.artifactRootPath();
        return new GraphPublicationReader(graph, registry, root == null ? (ArtifactFileStore) null : ArtifactFileStore.at(root), publications);
    }

    @Bean
    GraphPublicationAuthority graphPublicationAuthority(DocumentRegistryRepository registry, DocumentReadProperties properties,
            DisclosureExclusionReader exclusions, Clock clock, ApplicationContext context) {
        boolean install = !(context instanceof WebApplicationContext)
                && context.getEnvironment().getProperty("zoop.graph-delivery.install.enabled", Boolean.class, false);
        return new GraphPublicationAuthority(registry, new DocumentReadSources(properties.ingestionSourcesPath(!install)), exclusions, clock);
    }

    @Bean
    @ConditionalOnProperty(prefix = "zoop.graph-publication-compose", name = "enabled", havingValue = "true")
    ApplicationRunner graphPublicationComposeRunner(ApplicationContext context, GraphHandoffRepository graph,
            DocumentRegistryRepository registry, GraphVersionRepository versions, JdbcGraphPublicationRepository publications,
            GraphPublicationAuthority authority, DocumentReadProperties documentRead, TransactionOperations transaction, Clock clock) {
        Environment env = context.getEnvironment();
        if (context instanceof WebApplicationContext || "fixture".equals(env.getProperty("zoop.graph.snapshot.source")))
            throw new IllegalArgumentException("publication composition requires a nonweb artifact-mode process");
        for (String other : new String[] {"document-import", "document-analysis", "graph-handoff-import", "legacy-real-import", "disclosure-exclusion", "document-bindings"})
            if (env.getProperty("zoop." + other + ".enabled", Boolean.class, false))
                throw new IllegalArgumentException("publication composition requires exclusive operator execution");
        if (env.getProperty("zoop.graph-delivery.seal.enabled", Boolean.class, false)
                || env.getProperty("zoop.graph-delivery.install.enabled", Boolean.class, false))
            throw new IllegalArgumentException("publication composition requires exclusive delivery execution");
        Path root = path(env, "artifact-root"), request = path(env, "request"), decisions = path(env, "decisions"), result = path(env, "result");
        if (request.startsWith(root) || decisions.startsWith(root) || result.startsWith(root) || request.equals(result) || decisions.equals(result))
            throw new IllegalArgumentException("publication operator paths overlap");
        requireOwnedParent(result);
        ArtifactFileStore files = ArtifactFileStore.at(root);
        var reader = new GraphPublicationReader(graph, registry, files, publications);
        var composer = new GraphPublicationComposer(files, graph, registry, versions, publications, reader, authority,
                new DocumentReadSources(documentRead.ingestionSourcesPath()), transaction, clock);
        return args -> {
            try (FileChannel output = FileChannel.open(result, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
                ObjectNode answer;
                try {
                    answer = composer.run(PublicationComposeRequest.parse(readOperatorFile(request, PublicationComposeRequest.MAX_BYTES)),
                            readOperatorFile(decisions, 4_000_000));
                } catch (PublicationException invalid) { answer = GraphPublicationComposer.failed(invalid.code()); }
                ByteBuffer bytes = ByteBuffer.wrap(Canonical.bytes(answer));
                while (bytes.hasRemaining()) output.write(bytes);
                output.force(true);
                if (!"succeeded".equals(answer.get("status").stringValue())) throw new IllegalStateException("publication composition refused; see operator result");
            } catch (IOException error) { throw new IllegalStateException("publication result unavailable"); }
        };
    }

    private static Path path(Environment env, String name) {
        Path path = Path.of(env.getRequiredProperty("zoop.graph-publication-compose." + name));
        if (!path.isAbsolute() || !path.equals(path.normalize())) throw new IllegalArgumentException("publication requires normalized absolute " + name);
        return path;
    }
    private static void requireOwnedParent(Path path) {
        try {
            Path parent = path.getParent();
            if (parent == null || !parent.equals(parent.toRealPath())) throw new IOException();
            PosixFileAttributes attrs = Files.readAttributes(parent, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (!attrs.isDirectory() || attrs.permissions().contains(PosixFilePermission.GROUP_WRITE)
                    || attrs.permissions().contains(PosixFilePermission.OTHERS_WRITE)) throw new IOException();
        } catch (IOException error) { throw new IllegalArgumentException("publication result parent unavailable"); }
    }
    static byte[] readOperatorFile(Path path, int max) {
        try {
            if (!path.equals(path.toRealPath())) throw new IOException();
            var attrs = Files.readAttributes(path, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (!attrs.isRegularFile() || attrs.size() > max || attrs.permissions().contains(PosixFilePermission.GROUP_WRITE)
                    || attrs.permissions().contains(PosixFilePermission.OTHERS_WRITE)) throw new IOException();
            try (var stream = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
                byte[] bytes = stream.readNBytes(max + 1);
                if (bytes.length > max) throw new IOException();
                return bytes;
            }
        } catch (IOException error) { throw new PublicationException("request_invalid"); }
    }
}
