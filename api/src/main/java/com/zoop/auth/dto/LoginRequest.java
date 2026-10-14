package com.zoop.auth.dto;

public record LoginRequest(String email, String password) {
    @Override
    public String toString() {
        return "LoginRequest[credentials=<redacted>]";
    }
}
