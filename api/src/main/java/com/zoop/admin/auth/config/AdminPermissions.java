package com.zoop.admin.auth.config;

import java.util.Map;
import java.util.Set;

/** Central role-to-permission policy. The approved admin role currently permits every admin operation. */
public final class AdminPermissions {
    private static final Map<String, Set<String>> ROLE_PERMISSIONS = Map.of(
            "admin", Set.of("admin:all"));

    private AdminPermissions() { }

    public static boolean can(String role, String permission) {
        return ROLE_PERMISSIONS.getOrDefault(role, Set.of()).contains("admin:all")
                || ROLE_PERMISSIONS.getOrDefault(role, Set.of()).contains(permission);
    }
}
