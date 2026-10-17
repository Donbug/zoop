package com.zoop.admin.auth.provision;

import java.util.Arrays;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/** One-shot, non-web operator entry point. Password input is accepted only from an interactive terminal. */
public final class AdminProvisioningRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(AdminProvisioningRunner.class);
    private final AdminProvisioningSettings settings;
    private final AdminPasswordReader passwords;
    private final AdminProvisioningService service;

    public AdminProvisioningRunner(AdminProvisioningSettings settings,
            AdminPasswordReader passwords, AdminProvisioningService service) {
        this.settings = settings;
        this.passwords = passwords;
        this.service = service;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        char[] password = passwords.readConfirmedPassword();
        try {
            String requestId = "admin-provision-" + UUID.randomUUID();
            String id = service.provision(settings.email(), settings.displayName(),
                    new String(password), requestId);
            log.info("Administrator account provisioned: id={}", id);
        } finally {
            Arrays.fill(password, '\0');
        }
    }
}
