package com.zoop.briefing.input;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.HexFormat;
import static java.nio.file.StandardOpenOption.*;

/** Private, content-addressed staging. A staged file is NOT a registered artifacts row. */
public final class FileBriefingInputStore {
    public record Staged(Path path, String sha256, long bytes) {
        @Override public String toString() { return "Staged[sha256=" + sha256 + ", bytes=" + bytes + "]"; }
    }
    private final Path directory;

    public FileBriefingInputStore(Path directory) throws IOException {
        directory = directory.toAbsolutePath().normalize();
        if (Files.isSymbolicLink(directory)) throw new IOException("Staging directory is a symlink");
        Files.createDirectories(directory, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        if (!Files.getPosixFilePermissions(directory).equals(PosixFilePermissions.fromString("rwx------")))
            throw new IOException("Staging directory must be private (0700)");
        this.directory = directory.toRealPath();
    }

    public Staged put(byte[] original) throws IOException {
        byte[] content = original.clone();
        String digest = sha256(content);
        Path destination = directory.resolve(digest + ".json");
        Path temporary = Files.createTempFile(directory, ".briefing-", ".tmp",
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        try {
            try (var channel = FileChannel.open(temporary, WRITE)) {
                var buffer = ByteBuffer.wrap(content);
                while (buffer.hasRemaining()) channel.write(buffer);
                channel.force(true);
            }
            try {
                // Hard-link creation is atomic and fails if destination exists. ATOMIC_MOVE can overwrite.
                Files.createLink(destination, temporary);
            } catch (FileAlreadyExistsException existing) {
                if (Files.isSymbolicLink(destination) || !Files.isRegularFile(destination, LinkOption.NOFOLLOW_LINKS)
                        || !Arrays.equals(Files.readAllBytes(destination), content))
                    throw new IOException("Existing input is corrupt; refusing overwrite", existing);
            }
            try (var dir = FileChannel.open(directory, READ)) { dir.force(true); }
            return new Staged(destination, digest, content.length);
        } finally {
            Files.deleteIfExists(temporary);
        }
    }

    public static String sha256(byte[] content) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content)); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
}
