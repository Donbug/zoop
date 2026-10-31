package com.zoop.graph.delivery;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.delivery.seal.GraphDeliverySealConfiguration;
import com.zoop.graph.delivery.install.GraphDeliveryInstallConfiguration;
import com.zoop.graph.delivery.seal.GraphPublicationSealRequest;
import com.zoop.common.json.Canonical;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.mock.env.MockEnvironment;
import static org.junit.jupiter.api.Assertions.*;

class GraphDeliveryOperatorBoundaryTest {
    @TempDir Path temp;

    @Test void resultReservationIsExclusiveAndAnInterruptedResultStaysEmpty() throws Exception {
        Path result = temp.toRealPath().resolve("result.json");
        try (var reserved = GraphDeliveryResultFile.reserve(result)) {
            assertEquals(0, Files.size(result));
            assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(result));
            assertEquals("result_unavailable", assertThrows(GraphDeliveryException.class,
                    () -> GraphDeliveryResultFile.reserve(result)).code());
        }
        assertEquals(0, Files.size(result));
        Path next = temp.toRealPath().resolve("next.json");
        try (var reserved = GraphDeliveryResultFile.reserve(next)) {
            var document = StrictJson.newObject().put("status", "succeeded");
            reserved.write(document);
            assertThrows(GraphDeliveryException.class, () -> reserved.write(document));
        }
        assertEquals("succeeded", StrictJson.parseObject(Files.readAllBytes(next)).string("status"));
    }

    @Test void schemaGuardRequiresExplicitValidationOnlyStartup() {
        assertEquals("schema_mismatch", assertThrows(GraphDeliveryException.class,
                () -> GraphDeliverySchemaGuard.requireNoMigration(new MockEnvironment())).code());
        assertDoesNotThrow(() -> GraphDeliverySchemaGuard.requireNoMigration(new MockEnvironment().withProperty("spring.flyway.enabled", "false")));
        for (String property : List.of("spring.flyway.enabled=true", "spring.jpa.hibernate.ddl-auto=update", "spring.sql.init.mode=always")) {
            String[] pair = property.split("=");
            var env = new MockEnvironment().withProperty("spring.flyway.enabled", "false").withProperty(pair[0], pair[1]);
            assertEquals("schema_mismatch", assertThrows(GraphDeliveryException.class, () -> GraphDeliverySchemaGuard.requireNoMigration(env)).code());
        }
    }

    @Test void bothCommandsRefuseStartupWritersBeforeAnySingletonSideEffect() {
        for (String command : List.of("seal", "install")) {
            for (String conflict : List.of("zoop.document-import.enabled=true", "zoop.document-analysis.enabled=true",
                    "zoop.disclosure-exclusion.enabled=true", "zoop.legacy-real-import.enabled=true", "zoop.document-bindings.enabled=true",
                    "zoop.briefing.replay.import-enabled=true", "zoop.graph.auto-activation.enabled=true",
                    "zoop.graph-publication-compose.enabled=true", "zoop.graph.snapshot.source=fixture",
                    "zoop.graph-delivery." + (command.equals("seal") ? "install" : "seal") + ".enabled=true")) {
                refused(command, "configuration_invalid", conflict);
            }
            refused(command, "schema_mismatch", "spring.flyway.enabled=true");
        }
        refused("install", "configuration_invalid", "zoop.graph-handoff-import.enabled=true");
        refused("install", "configuration_invalid", "zoop.ai.handoff-read-client.enabled=true");
    }

    @Test void publicationSealRequestIsClosedAndPinsDestinationReceiptAndOperator() {
        var root = StrictJson.newObject().put("schemaVersion", "zoop-graph-publication-seal-1")
                .put("graphVersionId", "gv-" + "a".repeat(64)).put("expectedReceiptSha256", "b".repeat(64))
                .put("destinationId", "serving-a").put("operator", "synthetic-operator");
        var parsed = GraphPublicationSealRequest.parse(Canonical.bytes(root));
        assertEquals("serving-a", parsed.destinationId());
        assertEquals("b".repeat(64), parsed.expectedReceiptSha256());
        for (String extra : List.of("activation", "handoffId", "path", "bundle")) {
            var changed = root.deepCopy();
            changed.put(extra, "value");
            assertEquals("request_invalid", assertThrows(GraphDeliveryException.class,
                    () -> GraphPublicationSealRequest.parse(Canonical.bytes(changed))).code());
        }
        for (String field : List.of("schemaVersion", "graphVersionId", "expectedReceiptSha256", "destinationId", "operator")) {
            var changed = root.deepCopy();
            changed.remove(field);
            assertThrows(GraphDeliveryException.class, () -> GraphPublicationSealRequest.parse(Canonical.bytes(changed)));
        }
        assertThrows(GraphDeliveryException.class, () -> GraphPublicationSealRequest.parse(new byte[GraphPublicationSealRequest.MAX_BYTES + 1]));
        assertThrows(GraphDeliveryException.class, () -> GraphPublicationSealRequest.parse(
                "{\"schemaVersion\":\"one\",\"schemaVersion\":\"two\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8)));
    }

    @Test void publicationSealRefusesNativeImporterAndReadClientBeforeSingletons() {
        for (String conflict : List.of("zoop.graph-handoff-import.enabled=true", "zoop.ai.handoff-read-client.enabled=true")) {
            refused("seal", "configuration_invalid", "zoop.graph-delivery.seal.command=seal-publication", conflict);
        }
    }

    private void refused(String command, String code, String... conflicts) {
        AtomicBoolean created = new AtomicBoolean();
        new ApplicationContextRunner().withUserConfiguration(command.equals("seal")
                        ? GraphDeliverySealConfiguration.class : GraphDeliveryInstallConfiguration.class)
                .withPropertyValues("zoop.graph-delivery." + command + ".enabled=true", "spring.flyway.enabled=false",
                        "zoop.graph-handoff-import.enabled=" + command.equals("seal"))
                .withPropertyValues(conflicts)
                .withBean("wouldWrite", Object.class, () -> { created.set(true); return new Object(); })
                .run(context -> {
                    assertFalse(created.get(), String.join(",", conflicts));
                    Throwable cause = context.getStartupFailure();
                    assertNotNull(cause, String.join(",", conflicts));
                    while (cause.getCause() != null) cause = cause.getCause();
                    assertInstanceOf(GraphDeliveryException.class, cause);
                    assertEquals(code, ((GraphDeliveryException) cause).code(), String.join(",", conflicts));
                });
    }
}
