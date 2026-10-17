package com.zoop.admin.auth.provision;

import java.time.Instant;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.repository.AdminAuthRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AdminProvisioningWriter {
    private final AdminAuthRepository admins;
    private final AdminAuditRepository audit;

    public AdminProvisioningWriter(AdminAuthRepository admins, AdminAuditRepository audit) {
        this.admins = admins;
        this.audit = audit;
    }

    /** Account creation and its audit outcome commit atomically. */
    @Transactional
    public boolean create(String id, String email, String emailKey, String displayName,
            String passwordHash, String requestId, Instant occurredAt) {
        boolean inserted = admins.insertPasswordAccount(id, email, emailKey,
                displayName, passwordHash, occurredAt);
        audit.recordProvisioning(inserted ? id : null, inserted ? "succeeded" : "denied",
                inserted ? null : "email_already_registered", requestId, occurredAt);
        return inserted;
    }
}
