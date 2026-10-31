package com.zoop.graph.delivery.install;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryLimits;

record GraphDeliveryInstallSettings(String destinationId, String versionId, String expectedPackageDigest,
        Path artifactRoot, Path result, String ingestionSources, GraphDeliveryLimits limits) {
    static GraphDeliveryInstallSettings of(GraphDeliveryInstallProperties p, String ingestionSources) {
        require(p.destinationId() != null && p.destinationId().matches("[a-z0-9][a-z0-9-]{0,63}"));
        require(p.versionId() != null && p.versionId().matches("gv-[0-9a-f]{64}"));
        require(p.expectedPackageDigest() != null && p.expectedPackageDigest().matches("[0-9a-f]{64}"));
        Path root = absolute(p.artifactRoot());
        Path result = absolute(p.result());
        try {
            require(Files.isDirectory(root) && root.equals(root.toRealPath()));
            require(result.getParent() != null && Files.isDirectory(result.getParent()));
            require(!result.getParent().toRealPath().startsWith(root));
            require(!Files.exists(result, LinkOption.NOFOLLOW_LINKS));
        } catch (IOException error) {
            throw new GraphDeliveryException("configuration_invalid");
        }
        require(p.maxFiles() > 0 && p.maxPackageBytes() > 0);
        return new GraphDeliveryInstallSettings(p.destinationId(), p.versionId(), p.expectedPackageDigest(), root,
                result, ingestionSources, new GraphDeliveryLimits(p.maxFiles(), p.maxPackageBytes(), Long.MAX_VALUE));
    }

    private static Path absolute(String value) {
        try {
            require(value != null && !value.isBlank());
            Path path = Path.of(value);
            require(path.isAbsolute() && path.equals(path.normalize()));
            return path;
        } catch (java.nio.file.InvalidPathException error) {
            throw new GraphDeliveryException("configuration_invalid");
        }
    }

    private static void require(boolean condition) {
        if (!condition) throw new GraphDeliveryException("configuration_invalid");
    }
}
