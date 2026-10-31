package com.zoop.graph.delivery.seal;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryLimits;
import com.zoop.graph.delivery.GraphDeliveryManifest;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties("zoop.graph-delivery.seal")
public record GraphDeliverySealProperties(@DefaultValue("false") boolean enabled, @DefaultValue("seal") String command,
        String destinationId, @DefaultValue("1003") int maxFiles, @DefaultValue("268435456") long maxPackageBytes,
        @DefaultValue("1073741824") long maxPendingBytes, String result, String request, String artifactRoot) {
    public void validate() {
        if (!("seal".equals(command) || "seal-publication".equals(command) || "status".equals(command))
                || !GraphDeliveryManifest.validDestination(destinationId)) {
            throw new GraphDeliveryException("configuration_invalid");
        }
        limits();
        resultPath();
        if ("seal-publication".equals(command)) {
            try {
                Path root = artifactRootPath();
                Path input = requestPath();
                if (!Files.isDirectory(root) || !root.equals(root.toRealPath()) || !Files.isRegularFile(input)
                        || !input.equals(input.toRealPath()) || input.startsWith(root)
                        || resultPath().getParent().toRealPath().startsWith(root)) {
                    throw new GraphDeliveryException("configuration_invalid");
                }
            } catch (IOException invalid) {
                throw new GraphDeliveryException("configuration_invalid");
            }
        }
    }

    public GraphDeliveryLimits limits() { return new GraphDeliveryLimits(maxFiles, maxPackageBytes, maxPendingBytes); }

    public Path resultPath() {
        try {
            Path path = Path.of(result);
            if (!path.isAbsolute() || !path.equals(path.normalize()) || path.getParent() == null
                    || !Files.isDirectory(path.getParent())) throw new GraphDeliveryException("configuration_invalid");
            return path;
        } catch (IllegalArgumentException | NullPointerException invalid) {
            throw new GraphDeliveryException("configuration_invalid");
        }
    }

    public Path requestPath() { return absolute(request); }

    public Path artifactRootPath() { return absolute(artifactRoot); }

    private static Path absolute(String value) {
        try {
            Path path = Path.of(value);
            if (!path.isAbsolute() || !path.equals(path.normalize())) throw new GraphDeliveryException("configuration_invalid");
            return path;
        } catch (IllegalArgumentException | NullPointerException invalid) {
            throw new GraphDeliveryException("configuration_invalid");
        }
    }

    @Override
    public String toString() { return "GraphDeliverySealProperties[enabled=" + enabled + "]"; }
}
