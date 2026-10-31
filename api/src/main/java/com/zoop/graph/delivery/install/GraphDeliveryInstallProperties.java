package com.zoop.graph.delivery.install;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** Explicit destination and package pins. */
@ConfigurationProperties("zoop.graph-delivery.install")
public record GraphDeliveryInstallProperties(@DefaultValue("false") boolean enabled, String destinationId,
        String versionId, String expectedPackageDigest, String artifactRoot, String result,
        @DefaultValue("1003") int maxFiles, @DefaultValue("268435456") long maxPackageBytes) {
    @Override
    public String toString() { return "GraphDeliveryInstallProperties[enabled=" + enabled + "]"; }
}
