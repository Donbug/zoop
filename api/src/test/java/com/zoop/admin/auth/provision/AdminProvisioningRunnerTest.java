package com.zoop.admin.auth.provision;

import org.junit.jupiter.api.Test;
import org.springframework.boot.DefaultApplicationArguments;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AdminProvisioningRunnerTest {
    @Test
    void clearsPasswordBufferAfterProvisioning() throws Exception {
        char[] password = "Safe admin password 2026".toCharArray();
        var service = mock(AdminProvisioningService.class);
        when(service.provision(anyString(), anyString(), anyString(), anyString()))
                .thenReturn("admin-1");
        var runner = new AdminProvisioningRunner(
                new AdminProvisioningSettings("admin@example.com", "운영 관리자"),
                () -> password, service);

        runner.run(new DefaultApplicationArguments());

        assertArrayEquals(new char[password.length], password);
        verify(service).provision(eq("admin@example.com"), eq("운영 관리자"),
                eq("Safe admin password 2026"), startsWith("admin-provision-"));
    }

    @Test
    void clearsPasswordBufferWhenProvisioningFails() {
        char[] password = "Safe admin password 2026".toCharArray();
        var service = mock(AdminProvisioningService.class);
        when(service.provision(anyString(), anyString(), anyString(), anyString()))
                .thenThrow(new AdminProvisioningException("failed"));
        var runner = new AdminProvisioningRunner(
                new AdminProvisioningSettings("admin@example.com", "운영 관리자"),
                () -> password, service);

        assertThrows(AdminProvisioningException.class,
                () -> runner.run(new DefaultApplicationArguments()));
        assertArrayEquals(new char[password.length], password);
    }
}
