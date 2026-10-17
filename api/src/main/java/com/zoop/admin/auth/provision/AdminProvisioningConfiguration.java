package com.zoop.admin.auth.provision;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Profiles;
import org.springframework.web.context.WebApplicationContext;

@Configuration(proxyBeanMethods = false)
@Profile("admin-provision")
public class AdminProvisioningConfiguration {
    @Bean
    AdminProvisioningSettings adminProvisioningSettings(
            @Value("${zoop.admin.provision.email:}") String email,
            @Value("${zoop.admin.provision.display-name:}") String displayName,
            ApplicationContext context) {
        if (context instanceof WebApplicationContext) {
            throw new AdminProvisioningException(
                    "Admin provisioning requires spring.main.web-application-type=none");
        }
        if (context.getEnvironment().acceptsProfiles(Profiles.of("catalog-import"))) {
            throw new AdminProvisioningException("Admin provisioning cannot run with catalog-import");
        }
        return new AdminProvisioningSettings(email, displayName);
    }

    @Bean
    AdminPasswordReader adminPasswordReader() {
        return new ConsoleAdminPasswordReader();
    }

    @Bean
    AdminProvisioningRunner adminProvisioningRunner(AdminProvisioningSettings settings,
            AdminPasswordReader passwords, AdminProvisioningService service) {
        return new AdminProvisioningRunner(settings, passwords, service);
    }
}
