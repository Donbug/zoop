package com.zoop.admin.auth.provision;

public record AdminProvisioningSettings(String email, String displayName) {
    public AdminProvisioningSettings {
        if (email == null || email.isBlank()) {
            throw new AdminProvisioningException("Set zoop.admin.provision.email");
        }
        if (displayName == null || displayName.isBlank()) {
            throw new AdminProvisioningException("Set zoop.admin.provision.display-name");
        }
    }
}
