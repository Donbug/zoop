package com.zoop.admin.auth.provision;

import java.time.Clock;
import java.util.UUID;

import com.zoop.auth.service.CredentialPolicy;
import com.zoop.auth.service.PasswordHashService;
import org.springframework.stereotype.Service;

@Service
public class AdminProvisioningService {
    private final CredentialPolicy credentials;
    private final PasswordHashService passwords;
    private final AdminProvisioningWriter writer;
    private final Clock clock;

    public AdminProvisioningService(CredentialPolicy credentials, PasswordHashService passwords,
            AdminProvisioningWriter writer, Clock clock) {
        this.credentials = credentials;
        this.passwords = passwords;
        this.writer = writer;
        this.clock = clock;
    }

    public String provision(String rawEmail, String rawDisplayName, String password, String requestId) {
        var email = credentials.email(rawEmail);
        String displayName = credentials.displayName(rawDisplayName);
        String passwordHash = passwords.hashNewPassword(password);
        String id = "admin-" + UUID.randomUUID();
        boolean inserted = writer.create(id, email.value(), email.key(), displayName,
                passwordHash, requestId, clock.instant());
        if (!inserted) {
            throw new AdminProvisioningException("Administrator account already exists");
        }
        return id;
    }
}
