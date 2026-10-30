package com.zoop.document.bindings;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.web.context.WebApplicationContext;

/**
 * Registers the operator document bindings export only when {@code zoop.document-bindings.enabled=true}. Unconfigured, the
 * application starts without any export setting and none of these beans exists. When enabled, an invalid setting fails startup
 * (closed) with a message that names the setting, not its value, and so does either of these:
 * <ul>
 * <li>a web application context: the export is an operator run (start it with {@code spring.main.web-application-type=none}),
 *     never something to run next to a server;</li>
 * <li>another operator command enabled in the same process: runners have no defined order and the first one that fails ends the
 *     JVM, so the exit code and the result file are only this run's when it is the only one.</li>
 * </ul>
 * The failure happens while beans are created, before a web server would start listening.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "zoop.document-bindings", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(DocumentBindingsProperties.class)
public class DocumentBindingsConfiguration {
    /** The other operator commands of this jar; one run per process. */
    static final String[] OTHER_OPERATOR_COMMANDS = {"zoop.document-import.enabled", "zoop.document-analysis.enabled",
            "zoop.graph-handoff-import.enabled", "zoop.disclosure-exclusion.enabled", "zoop.briefing.replay.import-enabled"};

    @Bean
    DocumentBindingsSettings documentBindingsSettings(DocumentBindingsProperties properties, ApplicationContext context) {
        if (context instanceof WebApplicationContext) {
            throw new DocumentBindingsConfigurationException("enabled",
                    "requires spring.main.web-application-type=none (no web server may run during an export)");
        }
        for (String other : OTHER_OPERATOR_COMMANDS) {
            if ("true".equalsIgnoreCase(context.getEnvironment().getProperty(other))) {
                throw new DocumentBindingsConfigurationException("enabled",
                        "cannot run together with " + other + " (one operator command per process)");
            }
        }
        return properties.toSettings();
    }

    @Bean
    DocumentBindingsRepository documentBindingsRepository(NamedParameterJdbcTemplate jdbc) {
        return new JdbcDocumentBindingsRepository(jdbc);
    }

    @Bean
    DocumentBindingsRunner documentBindingsRunner(DocumentBindingsSettings settings, DocumentBindingsRepository repository) {
        return new DocumentBindingsRunner(settings, new BindingSelectionParser(), new DocumentBindingsExporter(repository));
    }
}
