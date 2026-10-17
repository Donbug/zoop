package com.zoop.admin.auth.service;

public record AdminPrincipal(String adminId, String email, String displayName,
        String role, String sessionId) {
}
