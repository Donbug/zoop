package com.zoop.graph.delivery.install;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import javax.sql.DataSource;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryLimits;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.env.MockEnvironment;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class GraphDeliveryInstallRunnerTest {
    @TempDir Path temp;
    private GraphDeliveryInstallSettings settings;
    private GraphDeliveryInstaller installer;
    private GraphDeliveryInstallRunner runner;

    @BeforeEach void prepare() {
        settings = new GraphDeliveryInstallSettings("serving-test", "gv-" + "a".repeat(64), "b".repeat(64), temp,
                temp.resolve("result.json"), null, new GraphDeliveryLimits(1003, 268435456, Long.MAX_VALUE));
        installer = mock(GraphDeliveryInstaller.class);
        runner = new GraphDeliveryInstallRunner(settings, installer, mock(DataSource.class), new MockEnvironment());
    }

    @Test void recordsRedactedSuccessAndOwnerOnlyResult() throws Exception {
        when(installer.install(eq(settings), any())).thenReturn("installed");
        runner.run(null);
        var result = StrictJson.parseObject(Files.readAllBytes(settings.result()));
        assertEquals("succeeded", result.string("status"));
        assertEquals("installed", result.string("outcome"));
        assertEquals(settings.expectedPackageDigest(), result.string("packageDigest"));
        assertFalse(Files.readString(settings.result()).contains(temp.toString()));
        assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(settings.result()));
    }

    @ParameterizedTest @ValueSource(strings = {"source_authority_unavailable", "database_unavailable", "internal_error", "artifact_unavailable"})
    void distinguishesRecordedRefusalFromUnknownEffects(String code) throws Exception {
        when(installer.install(eq(settings), any())).thenThrow(new GraphDeliveryException(code));
        assertEquals(code, assertThrows(GraphDeliveryException.class, () -> runner.run(null)).code());
        var result = StrictJson.parseObject(Files.readAllBytes(settings.result()));
        assertEquals("failed", result.string("status"));
        assertEquals(code, result.object("failure").string("code"));
        assertEquals(code.equals("source_authority_unavailable"), result.bool("outcomeKnown"));
    }

    @Test void reservedResultRefusesAnotherRunBeforeInstaller() throws Exception {
        Files.writeString(settings.result(), "previous result");
        assertEquals("result_unavailable", assertThrows(GraphDeliveryException.class, () -> runner.run(null)).code());
        assertEquals("previous result", Files.readString(settings.result()));
        verifyNoInteractions(installer);
    }
}
