package com.zoop.graph.delivery;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Set;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;

/** An empty or incomplete reserved result is UNKNOWN. Reconcile with the same pins and a fresh result path. */
public final class GraphDeliveryResultFile implements AutoCloseable {
    private final FileChannel channel;

    private GraphDeliveryResultFile(FileChannel channel) { this.channel = channel; }

    public static GraphDeliveryResultFile reserve(Path path) {
        FileChannel channel = null;
        try {
            channel = FileChannel.open(path, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
            channel.force(true);
            try (FileChannel parent = FileChannel.open(path.getParent(), StandardOpenOption.READ)) {
                parent.force(true);
            }
            return new GraphDeliveryResultFile(channel);
        } catch (IOException | RuntimeException failure) {
            if (channel != null) {
                try { channel.close(); } catch (IOException closeFailure) { failure.addSuppressed(closeFailure); }
            }
            throw new GraphDeliveryException("result_unavailable");
        }
    }

    public void write(JsonNode result) {
        try {
            if (channel.position() != 0 || channel.size() != 0) throw new GraphDeliveryException("result_unavailable");
            ByteBuffer bytes = ByteBuffer.wrap(StrictJson.write(result));
            while (bytes.hasRemaining()) channel.write(bytes);
            channel.force(true);
        } catch (IOException failure) {
            throw new GraphDeliveryException("result_unavailable");
        }
    }

    @Override
    public void close() {
        try {
            channel.close();
        } catch (IOException failure) {
            throw new GraphDeliveryException("result_unavailable");
        }
    }
}
