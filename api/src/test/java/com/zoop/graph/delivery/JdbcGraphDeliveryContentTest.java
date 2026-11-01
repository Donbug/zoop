package com.zoop.graph.delivery;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.time.Instant;
import javax.sql.DataSource;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.repository.ArtifactRow;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

class JdbcGraphDeliveryContentTest {
    private final byte[] body = "synthetic-byte-body".getBytes(StandardCharsets.UTF_8);
    private final ArtifactRow row = new ArtifactRow("artifact-one", "extracted_text", "artifact-root:extracted_text/one.txt",
            ArtifactFileStore.sha256(body), body.length, "text/plain", Instant.EPOCH);
    private final DataSource dataSource = mock(DataSource.class);
    private final Connection connection = mock(Connection.class);
    private final PreparedStatement statement = mock(PreparedStatement.class);
    private final ResultSet result = mock(ResultSet.class);
    private JdbcGraphDeliveryStore store;

    @BeforeEach void prepare() throws Exception {
        when(dataSource.getConnection()).thenReturn(connection);
        when(connection.prepareStatement(anyString())).thenReturn(statement);
        when(statement.executeQuery()).thenReturn(result);
        when(result.next()).thenReturn(true);
        when(result.getString(1)).thenReturn(row.sha256());
        when(result.getLong(2)).thenReturn(row.bytes());
        when(result.getLong(3)).thenReturn(row.bytes());
        when(result.getBytes(4)).thenReturn(body);
        store = new JdbcGraphDeliveryStore(new JdbcTemplate(dataSource));
    }

    @Test void boundedSuccessfulReadReturnsTheDriverArrayWithoutCopying() throws Exception {
        assertSame(body, store.readContent(row));
        closed();
    }

    @Test void mismatchedPinsRefuseBeforeMaterializingBodyAndCloseResources() throws Exception {
        when(result.getString(1)).thenReturn("f".repeat(64));
        assertEquals("package_invalid", assertThrows(GraphDeliveryException.class, () -> store.readContent(row)).code());
        verify(result, never()).getBytes(anyInt());
        closed();
    }

    @Test void mismatchedStoredLengthRefusesBeforeMaterializingBody() throws Exception {
        when(result.getLong(3)).thenReturn(row.bytes() + 1);
        assertEquals("package_invalid", assertThrows(GraphDeliveryException.class, () -> store.readContent(row)).code());
        verify(result, never()).getBytes(anyInt());
        closed();
    }

    @Test void corruptBodyRefusesAfterHashing() throws Exception {
        byte[] corrupted = body.clone();
        corrupted[0] ^= 1;
        when(result.getBytes(4)).thenReturn(corrupted);
        assertEquals("package_invalid", assertThrows(GraphDeliveryException.class, () -> store.readContent(row)).code());
        closed();
    }

    @Test void oversizedExpectedContentRefusesBeforeConnecting() throws Exception {
        var oversized = new ArtifactRow(row.id(), row.kind(), row.storageUri(), row.sha256(), ArtifactFileStore.MAX_READ_BYTES + 1,
                row.mediaType(), row.createdAt());
        assertEquals("package_too_large", assertThrows(GraphDeliveryException.class, () -> store.readContent(oversized)).code());
        verify(dataSource, never()).getConnection();
    }

    private void closed() throws Exception {
        verify(result).close();
        verify(statement).close();
        verify(connection).close();
    }
}
