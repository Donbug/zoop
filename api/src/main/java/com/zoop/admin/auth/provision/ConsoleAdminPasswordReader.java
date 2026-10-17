package com.zoop.admin.auth.provision;

import java.io.Console;
import java.util.Arrays;

public final class ConsoleAdminPasswordReader implements AdminPasswordReader {
    @Override
    public char[] readConfirmedPassword() {
        Console console = System.console();
        if (console == null) {
            throw new AdminProvisioningException(
                    "Interactive terminal required; run the packaged application with java -jar");
        }
        char[] password = console.readPassword("Administrator password: ");
        char[] confirmation = console.readPassword("Confirm administrator password: ");
        if (password == null || confirmation == null) {
            clear(password);
            clear(confirmation);
            throw new AdminProvisioningException("Password input was cancelled");
        }
        if (!Arrays.equals(password, confirmation)) {
            clear(password);
            clear(confirmation);
            throw new AdminProvisioningException("Password confirmation does not match");
        }
        clear(confirmation);
        return password;
    }

    private static void clear(char[] value) {
        if (value != null) {
            Arrays.fill(value, '\0');
        }
    }
}
