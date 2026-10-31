package com.zoop.graph.delivery;

import java.util.List;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.repository.ArtifactRow;

public record GraphDeliveryLimits(int maxFiles, long maxPackageBytes, long maxPendingBytes) {
    public static final int DEFAULT_MAX_FILES = 1003;
    public static final long DEFAULT_MAX_PACKAGE_BYTES = 256L * 1024 * 1024;
    public static final long DEFAULT_MAX_PENDING_BYTES = 1024L * 1024 * 1024;

    public GraphDeliveryLimits {
        if (maxFiles < 2 || maxFiles > DEFAULT_MAX_FILES || maxPackageBytes < 1 || maxPendingBytes < 1) {
            throw new GraphDeliveryException("configuration_invalid");
        }
    }

    public void checkPackage(List<ArtifactRow> rows) {
        if (rows.size() > maxFiles) throw new GraphDeliveryException("package_too_large");
        long total = 0;
        for (ArtifactRow row : rows) {
            if (row.bytes() < 0 || row.bytes() > ArtifactFileStore.MAX_READ_BYTES
                    || row.bytes() > maxPackageBytes - total) throw new GraphDeliveryException("package_too_large");
            total += row.bytes();
        }
    }

    public void checkPending(long pending, long added) {
        if (pending < 0 || added < 0 || pending > maxPendingBytes || added > maxPendingBytes - pending) {
            throw new GraphDeliveryException("outbox_full");
        }
    }
}
