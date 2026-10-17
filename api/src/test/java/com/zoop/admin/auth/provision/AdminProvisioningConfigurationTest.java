package com.zoop.admin.auth.provision;

import org.junit.jupiter.api.Test;
import org.springframework.context.support.GenericApplicationContext;
import org.springframework.web.context.WebApplicationContext;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

class AdminProvisioningConfigurationTest {
    private final AdminProvisioningConfiguration configuration = new AdminProvisioningConfiguration();

    @Test
    void acceptsOnlyConfiguredNonWebOperatorRun() {
        try (var context = new GenericApplicationContext()) {
            context.getEnvironment().setActiveProfiles("admin-provision");
            var settings = configuration.adminProvisioningSettings(
                    "admin@example.com", "운영 관리자", context);
            assertEquals("admin@example.com", settings.email());
            assertEquals("운영 관리자", settings.displayName());
        }
    }

    @Test
    void rejectsWebApplicationContext() {
        var error = assertThrows(AdminProvisioningException.class,
                () -> configuration.adminProvisioningSettings("admin@example.com", "운영 관리자",
                        mock(WebApplicationContext.class)));
        assertTrue(error.getMessage().contains("web-application-type=none"));
    }

    @Test
    void rejectsCatalogImportProfileAndMissingIdentityOptions() {
        try (var context = new GenericApplicationContext()) {
            context.getEnvironment().setActiveProfiles("admin-provision", "catalog-import");
            assertThrows(AdminProvisioningException.class,
                    () -> configuration.adminProvisioningSettings(
                            "admin@example.com", "운영 관리자", context));
        }
        assertThrows(AdminProvisioningException.class,
                () -> new AdminProvisioningSettings("", "운영 관리자"));
        assertThrows(AdminProvisioningException.class,
                () -> new AdminProvisioningSettings("admin@example.com", ""));
    }
}
