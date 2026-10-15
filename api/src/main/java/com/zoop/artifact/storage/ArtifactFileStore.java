package com.zoop.artifact.storage;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.DirectoryStream;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.OpenOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.FileAttribute;
import java.nio.file.attribute.PosixFileAttributes;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.attribute.UserPrincipal;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Local-filesystem artifact content under one operator-configured root: immutable, id-addressed, never overwritten.
 *
 * <p>The root must be an existing real POSIX directory that is not group- or world-writable. The root, lock, content
 * directories and files must retain one owner; existing entries with weaker permissions are rejected, never silently
 * repaired. Every write goes through a {@link Session}, which holds an exclusive 0600 lock on
 * {@code <root>/.document-import.lock} for its whole life, so no other importer can create, adopt or compensate (delete)
 * a file concurrently.
 *
 * <p>A file is written to a random 0600 temporary name, fsynced and then hard-linked to its final name; {@code link}
 * never replaces an existing file. An existing final file is only adopted when it is an owner-matching 0600 regular
 * file with identical bytes. Before either a new file or a recovered orphan is returned, the file data and every
 * directory entry created by this store have crossed their applicable fsync barriers.
 *
 * <p>A file name or directory that is not a plain identifier is rejected, so no input can traverse out of the root.
 * Paths never appear in an exception message; the stored URI is relative ({@code artifact-root:<dir>/<name>}).
 */
public final class ArtifactFileStore {
    public static final String LOCK_FILE = ".document-import.lock";
    public static final String URI_SCHEME = "artifact-root:";
    /** The largest file {@link Session#read} returns; every document, result and receipt of this app is far smaller. */
    public static final long MAX_READ_BYTES = 16L * 1024 * 1024;

    private static final Pattern DIRECTORY = Pattern.compile("[a-z][a-z0-9_]{0,63}");
    private static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");
    private static final Pattern FILE_NAME = Pattern.compile("[A-Za-z0-9][A-Za-z0-9_-]{0,127}\\.[a-z0-9]{1,8}");
    private static final Set<PosixFilePermission> OWNER_FILE = PosixFilePermissions.fromString("rw-------");
    private static final Set<PosixFilePermission> OWNER_DIRECTORY =
            PosixFilePermissions.fromString("rwx------");
    private static final Set<OpenOption> FORCE_FILE_OPTIONS =
            Set.of(StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
    private static final FileAttribute<Set<PosixFilePermission>> OWNER_FILE_ATTRIBUTE =
            PosixFilePermissions.asFileAttribute(OWNER_FILE);
    private static final FileAttribute<Set<PosixFilePermission>> OWNER_DIRECTORY_ATTRIBUTE =
            PosixFilePermissions.asFileAttribute(OWNER_DIRECTORY);
    private static final ForceObserver NO_FORCE_OBSERVER = path -> {};
    private static final SecureRandom RANDOM = new SecureRandom();

    private final Path root;
    private final UserPrincipal rootOwner;
    private final ForceObserver forceObserver;

    private ArtifactFileStore(Path root, UserPrincipal rootOwner, ForceObserver forceObserver) {
        this.root = root;
        this.rootOwner = rootOwner;
        this.forceObserver = forceObserver;
    }

    /** The root must be absolute, real, POSIX, and not writable by any principal other than its owner. */
    public static ArtifactFileStore at(Path root) {
        return at(root, NO_FORCE_OBSERVER);
    }

    static ArtifactFileStore at(Path root, ForceObserver forceObserver) {
        try {
            if (!root.isAbsolute() || !root.equals(root.toRealPath())) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "root");
            }
            PosixFileAttributes attributes = requireRoot(root, null);
            return new ArtifactFileStore(root, attributes.owner(), Objects.requireNonNull(forceObserver));
        } catch (IOException | UnsupportedOperationException | SecurityException error) {
            throw unavailable(error);
        }
    }

    /** Takes the operator lock; {@link ArtifactStoreException.Reason#BUSY} when another importer holds it. */
    public Session open() {
        try {
            requireRoot(root, rootOwner);
        } catch (IOException | UnsupportedOperationException | SecurityException error) {
            throw unavailable(error);
        }
        Path lockPath = root.resolve(LOCK_FILE);
        FileChannel channel = null;
        try {
            channel = FileChannel.open(lockPath, Set.of(StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS), OWNER_FILE_ATTRIBUTE);
            PosixFileAttributes attributes = Files.readAttributes(lockPath, PosixFileAttributes.class,
                    LinkOption.NOFOLLOW_LINKS);
            if (!attributes.isRegularFile() || !OWNER_FILE.equals(attributes.permissions())
                    || !rootOwner.equals(attributes.owner())) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "lock");
            }
            FileLock lock = channel.tryLock();
            if (lock == null) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.BUSY, "lock");
            }
            return new Session(root, rootOwner, forceObserver, channel, lock);
        } catch (OverlappingFileLockException error) {
            closeQuietly(channel);
            throw new ArtifactStoreException(ArtifactStoreException.Reason.BUSY, "lock");
        } catch (IOException | UnsupportedOperationException | SecurityException error) {
            closeQuietly(channel);
            throw unavailable(error);
        } catch (RuntimeException error) {
            closeQuietly(channel);
            throw error;
        }
    }

    /**
     * Read-only variant of {@link Session#read} for a reader that holds no session: the same checks (regular owner-matching
     * 0600 file in an owner-matching 0700 directory, exactly {@code bytes} long, hashing to {@code sha256}, at most
     * {@value #MAX_READ_BYTES} bytes) and the same failure reasons, plus the root's own checks. It takes no lock and never
     * creates, repairs, syncs or deletes anything: not the lock file, not a directory, not a temporary file. An operator
     * session may run at the same time, because a final file is only ever linked into place complete and never changed.
     */
    public byte[] readVerified(String uri, String sha256, long bytes) {
        try {
            requireRoot(root, rootOwner);
        } catch (IOException | UnsupportedOperationException | SecurityException error) {
            throw unavailable(error);
        }
        return readVerified(root, rootOwner, uri, sha256, bytes);
    }

    private static byte[] readVerified(Path root, UserPrincipal rootOwner, String uri, String sha256, long bytes) {
        if (uri == null || !uri.startsWith(URI_SCHEME) || sha256 == null || !SHA256.matcher(sha256).matches()
                || bytes < 0 || bytes > MAX_READ_BYTES) {
            throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "uri");
        }
        String relative = uri.substring(URI_SCHEME.length());
        int slash = relative.indexOf('/');
        if (slash <= 0 || relative.indexOf('/', slash + 1) >= 0) {
            throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "uri");
        }
        String directory = relative.substring(0, slash);
        String fileName = relative.substring(slash + 1);
        if (!DIRECTORY.matcher(directory).matches() || !FILE_NAME.matcher(fileName).matches()) {
            throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "name");
        }
        try {
            Path folder = root.resolve(directory);
            PosixFileAttributes directoryAttributes = attributesOrConflict(folder);
            if (!directoryAttributes.isDirectory() || !OWNER_DIRECTORY.equals(directoryAttributes.permissions())
                    || !rootOwner.equals(directoryAttributes.owner())) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "directory");
            }
            Path target = folder.resolve(fileName);
            PosixFileAttributes attributes = attributesOrConflict(target);
            if (!attributes.isRegularFile()) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.CONFLICT, "file");
            }
            if (!OWNER_FILE.equals(attributes.permissions()) || !rootOwner.equals(attributes.owner())) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "file");
            }
            if (attributes.size() != bytes) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.CONFLICT, "file");
            }
            byte[] content = readBounded(target, bytes);
            if (content.length != bytes || !sha256(content).equals(sha256)) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.CONFLICT, "file");
            }
            return content;
        } catch (ArtifactStoreException error) {
            throw error;
        } catch (NoSuchFileException vanished) {
            throw new ArtifactStoreException(ArtifactStoreException.Reason.CONFLICT, "missing");
        } catch (IOException | UnsupportedOperationException | SecurityException error) {
            throw unavailable(error);
        }
    }

    private static PosixFileAttributes attributesOrConflict(Path path) throws IOException {
        try {
            return Files.readAttributes(path, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        } catch (NoSuchFileException absent) {
            throw new ArtifactStoreException(ArtifactStoreException.Reason.CONFLICT, "missing");
        }
    }

    /** Content that is in the store, whether this session created it or found it. */
    public static final class StoredFile {
        private final Path path;
        private final String uri;
        private final String sha256;
        private final long bytes;
        private final boolean created;

        private StoredFile(Path path, String uri, String sha256, long bytes, boolean created) {
            this.path = path;
            this.uri = uri;
            this.sha256 = sha256;
            this.bytes = bytes;
            this.created = created;
        }

        public String uri() {
            return uri;
        }

        public String sha256() {
            return sha256;
        }

        public long bytes() {
            return bytes;
        }

        /** True only when this session made the final file; an adopted identical file is not "created". */
        public boolean created() {
            return created;
        }

        @Override
        public String toString() {
            return "StoredFile[" + uri + ", created=" + created + "]";
        }
    }

    @FunctionalInterface
    interface ForceObserver {
        /**
         * Test fault seam invoked only after the real file or directory force succeeds. Production uses a static no-op.
         */
        void afterForce(Path path) throws IOException;
    }

    public static final class Session implements AutoCloseable {
        private final Path root;
        private final UserPrincipal rootOwner;
        private final ForceObserver forceObserver;
        private final FileChannel channel;
        private final FileLock lock;

        private Session(Path root, UserPrincipal rootOwner, ForceObserver forceObserver, FileChannel channel, FileLock lock) {
            this.root = root;
            this.rootOwner = rootOwner;
            this.forceObserver = forceObserver;
            this.channel = channel;
            this.lock = lock;
        }

        /**
         * Stores {@code content} as {@code <root>/<directory>/<fileName>}. An existing owner-matching 0600 regular file
         * with identical bytes is adopted ({@code created() == false}); an insecure entry is unavailable, while a
         * different object or different bytes are a {@link ArtifactStoreException.Reason#CONFLICT}. Existing entries are
         * never changed.
         */
        public StoredFile put(String directory, String fileName, byte[] content) {
            if (!DIRECTORY.matcher(directory).matches() || !FILE_NAME.matcher(fileName).matches()) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "name");
            }
            String digest = sha256(content);
            String uri = URI_SCHEME + directory + "/" + fileName;
            try {
                Path folder = ensureDirectory(directory);
                Path target = folder.resolve(fileName);
                if (matchesExisting(target, content)) {
                    syncAdopted(target, folder);
                    return new StoredFile(target, uri, digest, content.length, false);
                }
                deleteStaleTemporaries(folder, fileName);
                Path temporary = folder.resolve("." + fileName + "." + HexFormat.of().formatHex(randomBytes()) + ".tmp");
                boolean created = false;
                try {
                    try (FileChannel out = FileChannel.open(temporary, Set.of(StandardOpenOption.CREATE_NEW,
                            StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS), OWNER_FILE_ATTRIBUTE)) {
                        ByteBuffer buffer = ByteBuffer.wrap(content);
                        while (buffer.hasRemaining()) {
                            out.write(buffer);
                        }
                        out.force(true);
                    }
                    try {
                        Files.createLink(target, temporary);
                        created = true;
                    } catch (FileAlreadyExistsException exists) {
                        if (matchesExisting(target, content)) {
                            syncAdopted(target, folder);
                            return new StoredFile(target, uri, digest, content.length, false);
                        }
                        throw new ArtifactStoreException(ArtifactStoreException.Reason.CONFLICT, "file");
                    }
                    Files.deleteIfExists(temporary);
                    syncDirectory(folder);
                    syncDirectory(root);
                    return new StoredFile(target, uri, digest, content.length, true);
                } catch (IOException | RuntimeException error) {
                    if (created) {
                        // This session made the final file and nothing durable depends on it yet.
                        deleteQuietly(target);
                    }
                    throw error;
                } finally {
                    deleteQuietly(temporary);
                }
            } catch (ArtifactStoreException error) {
                throw error;
            } catch (IOException | UnsupportedOperationException | SecurityException error) {
                throw unavailable(error);
            }
        }

        /**
         * Removes a file this session created, after confirming it is still a regular file with the same bytes. A file the
         * session merely adopted, or one that changed, is never touched. Returns whether the file was removed.
         */
        public boolean discard(StoredFile file) {
            if (!file.created()) {
                return false;
            }
            try {
                PosixFileAttributes attributes = Files.readAttributes(file.path, PosixFileAttributes.class,
                        LinkOption.NOFOLLOW_LINKS);
                if (!attributes.isRegularFile() || !OWNER_FILE.equals(attributes.permissions())
                        || !rootOwner.equals(attributes.owner()) || attributes.size() != file.bytes()
                        || !sha256(readBounded(file.path, file.bytes())).equals(file.sha256())) {
                    return false;
                }
                Files.delete(file.path);
            } catch (IOException | RuntimeException error) {
                return false;
            }
            try {
                syncDirectory(file.path.getParent());
            } catch (IOException ignored) {
                // The file is gone; only the directory entry's durability could not be confirmed.
            }
            return true;
        }

        /**
         * Reads a stored file back and verifies it against what the registry says about it: a regular owner-matching 0600 file
         * in an owner-matching 0700 directory, exactly {@code bytes} long and hashing to {@code sha256}. A missing file or any
         * size or hash difference is a {@link ArtifactStoreException.Reason#CONFLICT} (the registry and the file disagree);
         * an insecure entry is unavailable, as for {@link #put}. At most {@value #MAX_READ_BYTES} bytes are ever read.
         */
        public byte[] read(String uri, String sha256, long bytes) {
            return readVerified(root, rootOwner, uri, sha256, bytes);
        }

        @Override
        public void close() {
            try {
                lock.release();
            } catch (IOException ignored) {
                // Closing the channel below releases the lock as well.
            }
            closeQuietly(channel);
        }

        private Path ensureDirectory(String directory) throws IOException {
            Path folder = root.resolve(directory);
            PosixFileAttributes attributes;
            try {
                attributes = Files.readAttributes(folder, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            } catch (NoSuchFileException absent) {
                Files.createDirectory(folder, OWNER_DIRECTORY_ATTRIBUTE);
                attributes = Files.readAttributes(folder, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            }
            if (!attributes.isDirectory() || !OWNER_DIRECTORY.equals(attributes.permissions())
                    || !rootOwner.equals(attributes.owner())) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "directory");
            }
            return folder;
        }

        /** True when {@code target} holds exactly {@code content}; false when absent; conflict for anything else. */
        private boolean matchesExisting(Path target, byte[] content) throws IOException {
            PosixFileAttributes attributes;
            try {
                attributes = Files.readAttributes(target, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            } catch (NoSuchFileException absent) {
                return false;
            }
            if (!attributes.isRegularFile()) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.CONFLICT, "file");
            }
            if (!OWNER_FILE.equals(attributes.permissions()) || !rootOwner.equals(attributes.owner())) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "file");
            }
            if (attributes.size() != content.length
                    || !Arrays.equals(readBounded(target, content.length), content)) {
                throw new ArtifactStoreException(ArtifactStoreException.Reason.CONFLICT, "file");
            }
            return true;
        }

        private void deleteStaleTemporaries(Path folder, String fileName) throws IOException {
            // A crash can leave "<name>.<random>.tmp"; with the operator lock held no other importer owns one.
            try (DirectoryStream<Path> stale = Files.newDirectoryStream(folder, "." + fileName + ".*.tmp")) {
                for (Path candidate : stale) {
                    PosixFileAttributes attributes = Files.readAttributes(candidate, PosixFileAttributes.class,
                            LinkOption.NOFOLLOW_LINKS);
                    if (attributes.isRegularFile()) {
                        if (!OWNER_FILE.equals(attributes.permissions()) || !rootOwner.equals(attributes.owner())) {
                            throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "temporary");
                        }
                        Files.deleteIfExists(candidate);
                    }
                }
            }
        }

        private void syncAdopted(Path target, Path folder) throws IOException {
            syncFile(target);
            syncDirectory(folder);
            syncDirectory(root);
        }

        private void syncFile(Path file) throws IOException {
            forceFile(file);
            forceObserver.afterForce(file);
        }

        private void syncDirectory(Path directory) throws IOException {
            forceDirectory(directory);
            forceObserver.afterForce(directory);
        }
    }

    /** At most {@code expected + 1} bytes, so a larger file is detected without reading it whole. */
    private static byte[] readBounded(Path file, long expected) throws IOException {
        try (InputStream in = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS)) {
            return in.readNBytes((int) Math.min(expected + 1, Integer.MAX_VALUE));
        }
    }

    private static PosixFileAttributes requireRoot(Path root, UserPrincipal expectedOwner) throws IOException {
        PosixFileAttributes attributes = Files.readAttributes(root, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        Set<PosixFilePermission> permissions = attributes.permissions();
        if (!attributes.isDirectory() || permissions.contains(PosixFilePermission.GROUP_WRITE)
                || permissions.contains(PosixFilePermission.OTHERS_WRITE)
                || (expectedOwner != null && !expectedOwner.equals(attributes.owner()))) {
            throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "root");
        }
        return attributes;
    }

    private static void forceFile(Path file) throws IOException {
        try (FileChannel channel = FileChannel.open(file, FORCE_FILE_OPTIONS)) {
            channel.force(true);
        }
    }

    private static void forceDirectory(Path directory) throws IOException {
        try (FileChannel channel = FileChannel.open(directory, StandardOpenOption.READ)) {
            channel.force(true);
        }
    }

    private static byte[] randomBytes() {
        byte[] bytes = new byte[8];
        RANDOM.nextBytes(bytes);
        return bytes;
    }

    public static String sha256(byte[] content) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
    }

    private static ArtifactStoreException unavailable(Exception error) {
        return new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, error.getClass().getSimpleName());
    }

    private static void closeQuietly(FileChannel channel) {
        if (channel != null) {
            try {
                channel.close();
            } catch (IOException ignored) {
                // Nothing left to release.
            }
        }
    }

    private static void deleteQuietly(Path path) {
        try {
            Files.deleteIfExists(path);
        } catch (IOException ignored) {
            // A leftover temporary file is removed by the next write of the same name.
        }
    }
}
