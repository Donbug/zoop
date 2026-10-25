package com.zoop.admin.jobs;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.Clock;
import java.time.Duration;
import java.util.Locale;

import com.zoop.admin.jobs.AnalyzePlanState.ServiceBinding;
import com.zoop.ai.AiClientSettings;
import com.zoop.ai.config.AiExtractionClientProperties;
import com.zoop.ai.config.AiPlanAdmissionClientProperties;
import com.zoop.ai.config.AiRelationClientProperties;
import com.zoop.ai.http.HttpExtractionClient;
import com.zoop.ai.http.HttpPlanAdmissionClient;
import com.zoop.ai.http.HttpRelationClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AnalyzePlanProperties.class)
public class AnalyzePlanConfiguration {
    @Configuration(proxyBeanMethods = false)
    @ConditionalOnProperty(prefix = "zoop.analysis.analyze-plan", name = "enabled", havingValue = "true")
    @EnableConfigurationProperties({AiPlanAdmissionClientProperties.class, AiExtractionClientProperties.class,
            AiRelationClientProperties.class})
    static class Enabled {
        @Bean
        ServiceBinding analyzePlanServiceBinding(AnalyzePlanProperties properties,
                AiPlanAdmissionClientProperties admission, AiExtractionClientProperties extraction,
                AiRelationClientProperties relation, HttpPlanAdmissionClient admissionClient,
                HttpExtractionClient extractionClient, HttpRelationClient relationClient) {
            if (!admission.enabled() || !extraction.enabled() || !relation.enabled()) {
                throw new IllegalArgumentException("analyze-plan requires all three enabled production AI clients");
            }
            return validateBinding(properties, admission.toSettings(), extraction.toSettings(), relation.toSettings());
        }

        @Bean
        AnalyzePlanWorker analyzePlanWorker(JdbcAnalyzePlanRepository repository, HttpPlanAdmissionClient admission,
                HttpExtractionClient extraction, HttpRelationClient relation, Clock clock,
                AnalyzePlanProperties properties, ServiceBinding binding) {
            return new AnalyzePlanWorker(repository, admission, extraction, relation, clock, properties, binding);
        }

        @Bean
        AnalyzePlanScheduler analyzePlanScheduler(AnalyzePlanWorker worker, AnalyzePlanProperties properties) {
            return new AnalyzePlanScheduler(worker, properties.pollInterval());
        }
    }

    static ServiceBinding validateBinding(AnalyzePlanProperties properties, AiClientSettings admission,
            AiClientSettings extraction, AiClientSettings relation) {
        String base = canonicalBase(admission.baseUri());
        if (!base.equals(canonicalBase(extraction.baseUri())) || !base.equals(canonicalBase(relation.baseUri()))) {
            throw new IllegalArgumentException("analyze-plan requires one canonical AI base URL");
        }
        Duration largest = admission.requestTimeout().compareTo(extraction.requestTimeout()) > 0
                ? admission.requestTimeout() : extraction.requestTimeout();
        if (relation.requestTimeout().compareTo(largest) > 0) largest = relation.requestTimeout();
        if (properties.lease().compareTo(largest.plusSeconds(30)) < 0) {
            throw new IllegalArgumentException("zoop.analysis.analyze-plan.lease must cover the largest HTTP timeout plus 30s");
        }
        return ServiceBinding.of(base, properties.expectedPrincipal());
    }

    static String canonicalBase(URI uri) {
        String host = uri.getHost().toLowerCase(Locale.ROOT);
        if (host.endsWith(".")) throw new IllegalArgumentException("analyze-plan base URL DNS aliases are unsupported");
        String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
        int port = uri.getPort();
        if ((scheme.equals("https") && port == 443) || (scheme.equals("http") && port == 80)) port = -1;
        String path = uri.getRawPath();
        if (path == null || path.equals("/")) path = "";
        else if (path.endsWith("/")) path = path.substring(0, path.length() - 1);
        try {
            return new URI(scheme, null, host, port, path, null, null).toASCIIString();
        } catch (URISyntaxException invalid) {
            throw new IllegalArgumentException("analyze-plan base URL is unsupported");
        }
    }
}
