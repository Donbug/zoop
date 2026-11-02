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
import com.zoop.common.json.StrictJson;
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
        requireExclusiveOperator(context, "graph-publication-prepare");
        Path root = path(env, COMPOSE, "artifact-root"), request = path(env, COMPOSE, "request"), decisions = path(env, COMPOSE, "decisions"),
                result = path(env, COMPOSE, "result");
        if (request.startsWith(root) || decisions.startsWith(root) || result.startsWith(root) || request.equals(result) || decisions.equals(result))
            throw new IllegalArgumentException("publication operator paths overlap");
        requireOwnedParent(result);
        ArtifactFileStore files = ArtifactFileStore.at(root);
        var reader = new GraphPublicationReader(graph, registry, files, publications);
        var composer = new GraphPublicationComposer(files, graph, registry, versions, publications, reader, authority,
                new DocumentReadSources(documentRead.ingestionSourcesPath()), transaction, clock);
        return args -> writeOperatorResult(result, () -> {
            try {
                var parsed = PublicationComposeRequest.parse(readOperatorFile(request, PublicationComposeRequest.MAX_BYTES));
                byte[] decisionBytes = readOperatorFile(decisions, 4_000_000);
                // Automatic decisions go only with the preparation's operator name, and that name only with automatic decisions, so a
                // person's composition is never taken for a prepared one (whose sources set the next preparation's cutoff).
                if (refusedForOperator(parsed, decisionBytes)) return GraphPublicationComposer.failed("request_invalid");
                return composer.run(parsed, decisionBytes);
            } catch (PublicationException invalid) { return GraphPublicationComposer.failed(invalid.code()); }
        }, "publication composition refused; see operator result");
    }

    /**
     * The automatic preparation (#55): an operator run that builds the compose request and decisions itself and stages an inactive
     * candidate on top of the active publication. Same process rules as the operator composition; the two exclude each other.
     */
    @Bean
    @ConditionalOnProperty(prefix = "zoop.graph-publication-prepare", name = "enabled", havingValue = "true")
    ApplicationRunner graphPublicationPrepareRunner(ApplicationContext context, GraphHandoffRepository graph,
            DocumentRegistryRepository registry, GraphVersionRepository versions, JdbcGraphPublicationRepository publications,
            GraphPublicationAuthority authority, DocumentReadProperties documentRead, TransactionOperations transaction, Clock clock) {
        Environment env = context.getEnvironment();
        requireExclusiveOperator(context, "graph-publication-compose");
        Path root = path(env, PREPARE, "artifact-root"), result = path(env, PREPARE, "result");
        if (result.startsWith(root)) throw new IllegalArgumentException("publication operator paths overlap");
        requireOwnedParent(result);
        ArtifactFileStore files = ArtifactFileStore.at(root);
        var reader = new GraphPublicationReader(graph, registry, files, publications);
        var composer = new GraphPublicationComposer(files, graph, registry, versions, publications, reader, authority,
                new DocumentReadSources(documentRead.ingestionSourcesPath()), transaction, clock);
        var preparer = new GraphPublicationPreparer(versions, graph, publications, reader, composer);
        return args -> writeOperatorResult(result, preparer::run, "publication preparation stopped; see operator result");
    }

    /** Writes the operator result to a new owner-only file (never over an existing one) and fails the run when it did not succeed. */
    private static void writeOperatorResult(Path result, java.util.function.Supplier<ObjectNode> run, String refusal) {
        try (FileChannel output = FileChannel.open(result, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ObjectNode answer = run.get();
            ByteBuffer bytes = ByteBuffer.wrap(Canonical.bytes(answer));
            while (bytes.hasRemaining()) output.write(bytes);
            output.force(true);
            if (!"succeeded".equals(answer.get("status").stringValue())) throw new IllegalStateException(refusal);
        } catch (IOException error) { throw new IllegalStateException("publication result unavailable"); }
    }

    private static final String COMPOSE = "zoop.graph-publication-compose";
    private static final String PREPARE = "zoop.graph-publication-prepare";

    /** A nonweb artifact-mode process running exactly one operator command. */
    private static void requireExclusiveOperator(ApplicationContext context, String publicationSibling) {
        Environment env = context.getEnvironment();
        if (context instanceof WebApplicationContext || "fixture".equals(env.getProperty("zoop.graph.snapshot.source")))
            throw new IllegalArgumentException("publication composition requires a nonweb artifact-mode process");
        for (String other : new String[] {"document-import", "document-analysis", "graph-handoff-import", "legacy-real-import", "disclosure-exclusion",
                "document-bindings", publicationSibling})
            if (env.getProperty("zoop." + other + ".enabled", Boolean.class, false))
                throw new IllegalArgumentException("publication composition requires exclusive operator execution");
        if (env.getProperty("zoop.graph-delivery.seal.enabled", Boolean.class, false)
                || env.getProperty("zoop.graph-delivery.install.enabled", Boolean.class, false))
            throw new IllegalArgumentException("publication composition requires exclusive delivery execution");
    }

    private static Path path(Environment env, String prefix, String name) {
        Path path = Path.of(env.getRequiredProperty(prefix + "." + name));
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
    /**
     * The preparation's operator name goes only with the preparation's own decisions, so the recovery of an unknown outcome (the
     * prepared request and decision bytes from its result file) can be run as an operator compose; any other operator may not write the
     * automatic reviewer.
     */
    static boolean refusedForOperator(PublicationComposeRequest request, byte[] decisions) {
        if (!GraphPublicationPreparer.OPERATOR.equals(request.operator())) return claimsAutomaticReviewer(decisions);
        try {
            return !PublicationMerger.onlyAutomaticDecisions(StrictJson.parseObject(decisions));
        } catch (StrictJson.Malformed | IllegalArgumentException malformed) {
            return true;
        }
    }
    static boolean claimsAutomaticReviewer(byte[] decisions) {
        try {
            return PublicationMerger.claimsAutomaticReviewer(StrictJson.parseObject(decisions));
        } catch (StrictJson.Malformed | IllegalArgumentException malformed) {
            return false; // the composer refuses a malformed document as request_invalid
        }
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
