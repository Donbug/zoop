package com.zoop.admin.auth.provision;

@FunctionalInterface
public interface AdminPasswordReader {
    char[] readConfirmedPassword();
}
