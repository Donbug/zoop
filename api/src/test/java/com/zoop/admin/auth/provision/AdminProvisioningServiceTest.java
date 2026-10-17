package com.zoop.admin.auth.provision;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import com.zoop.auth.service.CredentialPolicy;
import com.zoop.auth.service.PasswordHashService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AdminProvisioningServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-17T04:00:00Z");

    @Test
    void normalizesAndHashesCredentialsBeforeWritingAnAdmin() {
        var writer = mock(AdminProvisioningWriter.class);
        when(writer.create(anyString(), anyString(), anyString(), anyString(),
                anyString(), anyString(), any())).thenReturn(true);
        var service = service(writer);

        String id = service.provision(" Admin@Example.COM ", " 운영 관리자 ",
                "Safe admin password 2026", "request-1");

        var hash = ArgumentCaptor.forClass(String.class);
        verify(writer).create(eq(id), eq("Admin@Example.COM"), eq("admin@example.com"),
                eq("운영 관리자"), hash.capture(), eq("request-1"), eq(NOW));
        assertTrue(id.startsWith("admin-"));
        assertTrue(hash.getValue().startsWith("{argon2id-v1}$argon2id$"));
        assertFalse(hash.getValue().contains("Safe admin password 2026"));
    }

    @Test
    void duplicateEmailFailsWithoutReportingCredentials() {
        var writer = mock(AdminProvisioningWriter.class);
        when(writer.create(anyString(), anyString(), anyString(), anyString(),
                anyString(), anyString(), any())).thenReturn(false);
        var service = service(writer);

        var error = assertThrows(AdminProvisioningException.class,
                () -> service.provision("admin@example.com", "운영 관리자",
                        "Safe admin password 2026", "request-2"));

        assertFalse(error.getMessage().contains("admin@example.com"));
        assertFalse(error.getMessage().contains("Safe admin password 2026"));
    }

    private static AdminProvisioningService service(AdminProvisioningWriter writer) {
        var credentials = new CredentialPolicy();
        return new AdminProvisioningService(credentials, new PasswordHashService(credentials),
                writer, Clock.fixed(NOW, ZoneOffset.UTC));
    }
}
