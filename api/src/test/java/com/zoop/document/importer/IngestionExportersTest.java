package com.zoop.document.importer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

import java.util.Map;
import java.util.Optional;

import com.zoop.ai.observation.ObservationExportClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.support.StaticListableBeanFactory;

/** The one source choice and exporter factory both operator imports share. */
class IngestionExportersTest {
    private static ObjectProvider<ObservationExportClient> clients(ObservationExportClient... present) {
        StaticListableBeanFactory beans = new StaticListableBeanFactory();
        for (int index = 0; index < present.length; index++) beans.addBean("client-" + index, present[index]);
        return beans.getBeanProvider(ObservationExportClient.class);
    }

    @Test
    void aBlankValueIsTheCliDefaultTheTwoNamesAreReadCaseInsensitivelyAndAnythingElseIsNoChoice() {
        for (String blank : new String[] {null, "", "  "}) {
            assertEquals(Optional.of(ObservationSource.CLI), ObservationSource.parse(blank));
        }
        for (Map.Entry<String, ObservationSource> entry : Map.of("cli", ObservationSource.CLI, " CLI ", ObservationSource.CLI,
                "http", ObservationSource.HTTP, "Http", ObservationSource.HTTP).entrySet()) {
            assertEquals(Optional.of(entry.getValue()), ObservationSource.parse(entry.getKey()), entry.getKey());
        }
        for (String other : new String[] {"grpc", "https", "cli,http", "0"}) {
            assertTrue(ObservationSource.parse(other).isEmpty(), other);
        }
    }

    @Test
    void httpWiresTheExportClientAndFailsWithTheCallersExceptionWithoutOneWhileCliIgnoresAnEnabledClient() {
        ObservationExportClient client = mock(ObservationExportClient.class);
        IngestionExporter cli = mock(IngestionExporter.class);

        assertInstanceOf(HttpIngestionExporter.class, IngestionExporters.forSource(ObservationSource.HTTP, () -> cli,
                clients(client), IllegalStateException::new));

        IllegalStateException missing = assertThrows(IllegalStateException.class, () -> IngestionExporters.forSource(
                ObservationSource.HTTP, () -> cli, clients(), () -> new IllegalStateException("observation-source")));
        assertEquals("observation-source", missing.getMessage());

        assertSame(cli, IngestionExporters.forSource(ObservationSource.CLI, () -> cli, clients(client), IllegalStateException::new),
                "the client of the web application sharing this environment does not disturb a cli run");
        assertSame(cli, IngestionExporters.forSource(ObservationSource.CLI, () -> cli, clients(), IllegalStateException::new));
    }
}
