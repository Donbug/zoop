package com.zoop.graph.round;

import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

import com.zoop.ai.AiClientConfigurationException;
import com.zoop.ai.AiClientSettings;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.plan.PlanIdentity;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;

/** Fingerprint of the round service route and authority; never the bearer credential itself. */
public record RoundServiceBinding(String digest) {
    public RoundServiceBinding {
        PipelineJob.requireDigest("roundServiceBinding", digest);
    }

    public static RoundServiceBinding of(AiClientSettings settings, String expectedPrincipal) {
        if (expectedPrincipal == null || !PlanIdentity.PRINCIPAL.matcher(expectedPrincipal).matches()) {
            throw new AiClientConfigurationException("expected-principal", "must identify the round service principal")
                    .under("zoop.ai.round-client");
        }
        var identity = StrictJson.newObject();
        identity.put("format", "zoop-app-round-service-binding-1");
        identity.put("baseUrl", canonicalBase(settings.baseUri()));
        identity.put("principal", expectedPrincipal);
        identity.put("credentialSha256", Canonical.sha256(settings.token().getBytes(StandardCharsets.UTF_8)));
        return new RoundServiceBinding(Canonical.digest(identity));
    }

    private static String canonicalBase(URI uri) {
        String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost().toLowerCase(Locale.ROOT);
        if (host.endsWith(".")) {
            throw new AiClientConfigurationException("base-url", "DNS aliases are unsupported for round recovery")
                    .under("zoop.ai.round-client");
        }
        int port = uri.getPort();
        if ((scheme.equals("https") && port == 443) || (scheme.equals("http") && port == 80)) port = -1;
        String path = uri.getRawPath();
        if (path == null || path.equals("/")) path = "";
        else if (path.endsWith("/")) path = path.substring(0, path.length() - 1);
        try {
            return new URI(scheme, null, host, port, path, null, null).toASCIIString();
        } catch (URISyntaxException invalid) {
            throw new AiClientConfigurationException("base-url", "is unsupported for round recovery")
                    .under("zoop.ai.round-client");
        }
    }
}
