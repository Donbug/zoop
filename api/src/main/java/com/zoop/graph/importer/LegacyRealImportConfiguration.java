package com.zoop.graph.importer;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.service.DocumentRegistrationService;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.util.Set;
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
@ConditionalOnProperty(prefix = "zoop.legacy-real-import", name = "enabled", havingValue = "true")
public class LegacyRealImportConfiguration {
    @Bean
    ApplicationRunner legacyRealImportRunner(ApplicationContext context, DocumentRegistryRepository registry,
            DocumentRegistrationService documents, GraphHandoffRepository graph, TransactionOperations transaction, Clock clock) {
        Environment env = context.getEnvironment();
        if (context instanceof WebApplicationContext || "fixture".equals(env.getProperty("zoop.graph.snapshot.source")))
            throw new IllegalArgumentException("legacy-real import requires a nonweb, nonfixture operator process");
        for (String other : new String[] {"document-import", "document-analysis", "graph-handoff-import", "disclosure-exclusion", "document-bindings"})
            if (env.getProperty("zoop." + other + ".enabled", Boolean.class, false))
                throw new IllegalArgumentException("legacy-real import requires exclusive operator execution");
        Path input = path(env, "package-root"), sources = path(env, "sources"), artifacts = path(env, "artifact-root");
        Path request = path(env, "request"), result = path(env, "result");
        if (artifacts.startsWith(input) || input.startsWith(artifacts) || result.startsWith(input) || result.startsWith(artifacts)
                || request.equals(result) || sources.equals(result)) throw new IllegalArgumentException("legacy-real import paths overlap");
        var importer = new LegacyRealImporter(input, sources, ArtifactFileStore.at(artifacts), registry, documents, graph, transaction, clock);
        return args -> {
            try (var output = FileChannel.open(result, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
                ObjectNode answer;
                try {
                    answer = importer.run(LegacyRealPackage.Request.parse(LegacyRealPackage.readFile(request)));
                } catch (LegacyRealPackage.Invalid denied) {
                    answer = failure(denied.getMessage());
                } catch (RuntimeException error) {
                    answer = failure("import_failed:" + error.getClass().getSimpleName());
                }
                ByteBuffer bytes = ByteBuffer.wrap(Canonical.bytes(answer));
                while (bytes.hasRemaining()) output.write(bytes);
                output.force(true);
                if (!"succeeded".equals(answer.get("status").asString())) throw new IllegalStateException("legacy-real import refused; see operator result");
            } catch (IOException error) { throw new IllegalStateException("legacy-real operator result unavailable"); }
        };
    }
    private static ObjectNode failure(String code) {
        ObjectNode answer = StrictJson.newObject(); answer.put("schemaVersion", "zoop-legacy-real-import-result-1");
        answer.put("status", "failed"); answer.put("code", code); return answer;
    }
    private static Path path(Environment env, String name) {
        String value = env.getRequiredProperty("zoop.legacy-real-import." + name);
        if (value.isBlank() || !Path.of(value).isAbsolute()) throw new IllegalArgumentException("legacy-real import requires absolute " + name);
        return Path.of(value).normalize();
    }
}
