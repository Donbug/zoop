package com.zoop.ai.config;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.AiClientConfigurationException;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * {@code zoop.ai.plaintext-http-hosts} ({@code ZOOP_AI_PLAINTEXT_HTTP_HOSTS}, comma separated): the exact host names every
 * AI client may also reach over plain {@code http}, besides loopback. Empty by default, so every other host needs
 * {@code https}. Only for an in-VPC service name without a certificate (dev Service Connect {@code ai}); the bearer token and
 * the response bodies then travel unencrypted inside the VPC. Each entry is a lower-case DNS name; a wildcard, a port, a scheme,
 * an IP address or a malformed name fails startup with the setting's name, when an enabled AI client builds its settings
 * ({@link #hosts()}), like every other AI client setting.
 */
@ConfigurationProperties("zoop.ai")
public record AiTransportProperties(List<String> plaintextHttpHosts) {
    static final String PREFIX = "zoop.ai";
    private static final Pattern LABEL = Pattern.compile("[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?");
    private static final Pattern NUMERIC = Pattern.compile("[0-9]+");

    public AiTransportProperties {
        plaintextHttpHosts = plaintextHttpHosts == null ? List.of() : plaintextHttpHosts;
    }

    /** The validated hosts {@link com.zoop.ai.AiClientSettings} checks; blank entries are ignored. */
    public Set<String> hosts() {
        Set<String> hosts = new LinkedHashSet<>();
        for (String entry : plaintextHttpHosts) {
            String host = entry == null ? "" : entry.strip();
            if (host.isEmpty()) {
                continue;
            }
            if (!validHost(host)) {
                throw new AiClientConfigurationException("plaintext-http-hosts", "must list lower-case host names only")
                        .under(PREFIX);
            }
            hosts.add(host);
        }
        return Set.copyOf(hosts);
    }

    private static boolean validHost(String host) {
        if (host.length() > 253 || host.endsWith(".")) {
            return false;
        }
        boolean numeric = true;
        for (String label : host.split("\\.", -1)) {
            if (!LABEL.matcher(label).matches()) {
                return false;
            }
            numeric &= NUMERIC.matcher(label).matches();
        }
        return !numeric;
    }
}
