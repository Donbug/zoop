package com.zoop.artifact.storage;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.stream.Stream;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ArtifactFileStoreTest {
    private static final String NAME = "text-" + "a".repeat(64) + ".txt";
    private static final byte[] TEXT = "삼성전자 \"인용\" \\ \uD83D\uDE00\n본문".getBytes(StandardCharsets.UTF_8);
    private static final Set<PosixFilePermission> OWNER_DIRECTORY =
            PosixFilePermissions.fromString("rwx------");
    private static final Set<PosixFilePermission> OWNER_FILE =
            PosixFilePermissions.fromString("rw-------");

    @TempDir
    Path temp;
    private Path root;
    private ArtifactFileStore store;

    @BeforeEach
    void setUp() throws IOException {
        // macOS temp directories live under the /var symlink; the store needs the real path.
        root = Files.createDirectory(temp.toRealPath().resolve("root"));
        store = ArtifactFileStore.at(root);
    }

    private ArtifactStoreException.Reason reason(Runnable action) {
        return assertThrows(ArtifactStoreException.class, action::run).reason();
    }

    private static String sha256(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private static void assertPermissions(Path path, Set<PosixFilePermission> expected) throws IOException {
        assertEquals(expected, Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS),
                path.getFileName().toString());
    }

    @Test
    void theRootMustBeAnAbsoluteRealDirectory() throws IOException {
        Path file = Files.createFile(temp.toRealPath().resolve("file"));
        Path link = Files.createSymbolicLink(temp.toRealPath().resolve("link"), root);

        assertEquals(ArtifactStoreException.Reason.UNAVAILABLE,
                reason(() -> ArtifactFileStore.at(Path.of("relative/root"))));
        assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> ArtifactFileStore.at(root.resolve("missing"))));
        assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> ArtifactFileStore.at(file)));
        assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> ArtifactFileStore.at(link)));
        Path parentLink = Files.createSymbolicLink(temp.toRealPath().resolve("parent-link"), root.getParent());
        assertEquals(ArtifactStoreException.Reason.UNAVAILABLE,
                reason(() -> ArtifactFileStore.at(parentLink.resolve("root"))));
    }

    @Test
    void aGroupOrWorldWritableRootIsRejectedWithoutChangingIt() throws IOException {
        for (String mode : List.of("rwxrwx---", "rwx---rwx")) {
            Set<PosixFilePermission> permissions = PosixFilePermissions.fromString(mode);
            Files.setPosixFilePermissions(root, permissions);

            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> ArtifactFileStore.at(root)), mode);
            assertEquals(permissions, Files.getPosixFilePermissions(root, LinkOption.NOFOLLOW_LINKS), mode);
        }
    }

    @Test
    void createsAnIdAddressedOwnerOnlyFileWithExactBytesAndARelativeUri() throws Exception {
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile file = session.put("extracted_text", NAME, TEXT);

            assertTrue(file.created());
            assertEquals("artifact-root:extracted_text/" + NAME, file.uri());
            assertEquals(sha256(TEXT), file.sha256());
            assertEquals(TEXT.length, file.bytes());
            Path stored = root.resolve("extracted_text").resolve(NAME);
            assertArrayEquals(TEXT, Files.readAllBytes(stored));
            assertPermissions(stored, OWNER_FILE);
            assertPermissions(root.resolve("extracted_text"), OWNER_DIRECTORY);
            assertFalse(file.toString().contains(root.toString()));
        }
    }

    @Test
    void leavesNoTemporaryFileBehind() throws Exception {
        try (ArtifactFileStore.Session session = store.open()) {
            session.put("extracted_text", NAME, TEXT);
        }
        try (Stream<Path> entries = Files.list(root.resolve("extracted_text"))) {
            assertEquals(List.of(NAME), entries.map(p -> p.getFileName().toString()).toList());
        }
    }

    @Test
    void anIdenticalExistingFileIsAdoptedWithoutBeingTouched() throws Exception {
        Path stored;
        FileTime modified;
        Object inode;
        try (ArtifactFileStore.Session session = store.open()) {
            session.put("extracted_text", NAME, TEXT);
            stored = root.resolve("extracted_text").resolve(NAME);
            Files.setLastModifiedTime(stored, FileTime.fromMillis(1_000_000_000_000L));
            modified = Files.getLastModifiedTime(stored);
            inode = Files.readAttributes(stored, "unix:ino").get("ino");

            ArtifactFileStore.StoredFile again = session.put("extracted_text", NAME, TEXT);

            assertFalse(again.created());
            assertEquals(sha256(TEXT), again.sha256());
        }
        assertEquals(modified, Files.getLastModifiedTime(stored));
        assertEquals(inode, Files.readAttributes(stored, "unix:ino").get("ino"));
    }

    @Test
    void differentBytesAreAConflictAndTheOriginalIsNeverOverwritten() throws Exception {
        try (ArtifactFileStore.Session session = store.open()) {
            session.put("extracted_text", NAME, TEXT);
            byte[] other = "다른 본문".getBytes(StandardCharsets.UTF_8);

            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.put("extracted_text", NAME, other)));
            // Same length, different content, is still a conflict.
            byte[] sameLength = TEXT.clone();
            sameLength[0] ^= 1;
            assertEquals(ArtifactStoreException.Reason.CONFLICT,
                    reason(() -> session.put("extracted_text", NAME, sameLength)));
        }
        assertArrayEquals(TEXT, Files.readAllBytes(root.resolve("extracted_text").resolve(NAME)));
    }

    @Test
    void aPreExistingTamperedFileIsNeverOverwrittenOrDiscarded() throws Exception {
        Path directory = Files.createDirectory(root.resolve("extracted_text"));
        Files.setPosixFilePermissions(directory, OWNER_DIRECTORY);
        Path stored = Files.write(directory.resolve(NAME), "tampered".getBytes(StandardCharsets.UTF_8));
        Files.setPosixFilePermissions(stored, OWNER_FILE);
        try (ArtifactFileStore.Session session = store.open()) {
            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.put("extracted_text", NAME, TEXT)));
        }
        assertEquals("tampered", Files.readString(stored));
        try (Stream<Path> entries = Files.list(directory)) {
            assertEquals(1, entries.count());
        }
    }

    @Test
    void anInsecureExistingDirectoryIsRejectedWithoutChangingItOrItsFile() throws Exception {
        Path directory = Files.createDirectory(root.resolve("extracted_text"));
        Set<PosixFilePermission> permissions = PosixFilePermissions.fromString("rwxrwx---");
        Files.setPosixFilePermissions(directory, permissions);
        Path orphan = Files.write(directory.resolve(NAME), TEXT);
        Files.setPosixFilePermissions(orphan, OWNER_FILE);
        FileTime modified = Files.getLastModifiedTime(orphan);
        Object inode = Files.readAttributes(orphan, "unix:ino").get("ino");

        try (ArtifactFileStore.Session session = store.open()) {
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE,
                    reason(() -> session.put("extracted_text", NAME, TEXT)));
        }

        assertEquals(permissions, Files.getPosixFilePermissions(directory, LinkOption.NOFOLLOW_LINKS));
        assertEquals(OWNER_FILE, Files.getPosixFilePermissions(orphan, LinkOption.NOFOLLOW_LINKS));
        assertEquals(modified, Files.getLastModifiedTime(orphan));
        assertEquals(inode, Files.readAttributes(orphan, "unix:ino").get("ino"));
        assertArrayEquals(TEXT, Files.readAllBytes(orphan));
    }

    @Test
    void anInsecureExistingFileIsRejectedWithoutChangingIt() throws Exception {
        Path directory = Files.createDirectory(root.resolve("extracted_text"));
        Files.setPosixFilePermissions(directory, OWNER_DIRECTORY);
        Path orphan = Files.write(directory.resolve(NAME), TEXT);
        Set<PosixFilePermission> permissions = PosixFilePermissions.fromString("rw-r--r--");
        Files.setPosixFilePermissions(orphan, permissions);
        FileTime modified = Files.getLastModifiedTime(orphan);
        Object inode = Files.readAttributes(orphan, "unix:ino").get("ino");

        try (ArtifactFileStore.Session session = store.open()) {
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE,
                    reason(() -> session.put("extracted_text", NAME, TEXT)));
        }

        assertEquals(permissions, Files.getPosixFilePermissions(orphan, LinkOption.NOFOLLOW_LINKS));
        assertEquals(modified, Files.getLastModifiedTime(orphan));
        assertEquals(inode, Files.readAttributes(orphan, "unix:ino").get("ino"));
        assertArrayEquals(TEXT, Files.readAllBytes(orphan));
    }

    @Test
    void aSecureCrashOrphanWithTheSameBytesIsAdoptedAndSurvivesCompensation() throws Exception {
        Path directory = Files.createDirectory(root.resolve("extracted_text"));
        Files.setPosixFilePermissions(directory, OWNER_DIRECTORY);
        Path orphan = Files.write(directory.resolve(NAME), TEXT);
        Files.setPosixFilePermissions(orphan, OWNER_FILE);
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile adopted = session.put("extracted_text", NAME, TEXT);

            assertFalse(adopted.created());
            assertFalse(session.discard(adopted));
        }
        assertEquals(OWNER_DIRECTORY, Files.getPosixFilePermissions(directory, LinkOption.NOFOLLOW_LINKS));
        assertEquals(OWNER_FILE, Files.getPosixFilePermissions(orphan, LinkOption.NOFOLLOW_LINKS));
        assertArrayEquals(TEXT, Files.readAllBytes(orphan));
    }

    @Test
    void anAdoptionDurabilityFailurePreventsSuccessAndLeavesTheOrphanUntouched() throws Exception {
        Path directory = Files.createDirectory(root.resolve("extracted_text"));
        Files.setPosixFilePermissions(directory, OWNER_DIRECTORY);
        Path orphan = Files.write(directory.resolve(NAME), TEXT);
        Files.setPosixFilePermissions(orphan, OWNER_FILE);
        FileTime modified = Files.getLastModifiedTime(orphan);
        Object inode = Files.readAttributes(orphan, "unix:ino").get("ino");
        List<Path> forced = new ArrayList<>();
        ArtifactFileStore failingStore = ArtifactFileStore.at(root, path -> {
            forced.add(path);
            if (path.equals(directory)) {
                throw new IOException("injected force failure");
            }
        });

        try (ArtifactFileStore.Session session = failingStore.open()) {
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE,
                    reason(() -> session.put("extracted_text", NAME, TEXT)));
        }

        assertEquals(List.of(orphan, directory), forced);
        assertEquals(OWNER_FILE, Files.getPosixFilePermissions(orphan, LinkOption.NOFOLLOW_LINKS));
        assertEquals(modified, Files.getLastModifiedTime(orphan));
        assertEquals(inode, Files.readAttributes(orphan, "unix:ino").get("ino"));
        assertArrayEquals(TEXT, Files.readAllBytes(orphan));
    }

    @Test
    void symlinksAndDirectoriesAtTheFinalNameAreConflictsNeverAdopted() throws Exception {
        Path directory = Files.createDirectory(root.resolve("extracted_text"));
        Files.setPosixFilePermissions(directory, OWNER_DIRECTORY);
        Path outside = Files.write(temp.toRealPath().resolve("outside.txt"), TEXT);
        Files.createSymbolicLink(directory.resolve(NAME), outside);
        String other = "text-" + "b".repeat(64) + ".txt";
        Files.createDirectory(directory.resolve(other));
        String dangling = "text-" + "c".repeat(64) + ".txt";
        Files.createSymbolicLink(directory.resolve(dangling), temp.toRealPath().resolve("does-not-exist"));

        try (ArtifactFileStore.Session session = store.open()) {
            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.put("extracted_text", NAME, TEXT)));
            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.put("extracted_text", other, TEXT)));
            assertEquals(ArtifactStoreException.Reason.CONFLICT,
                    reason(() -> session.put("extracted_text", dangling, TEXT)));
        }
        assertArrayEquals(TEXT, Files.readAllBytes(outside));
        assertFalse(Files.exists(temp.toRealPath().resolve("does-not-exist")));
    }

    @Test
    void namesAndDirectoriesCannotTraverseOrHide() {
        try (ArtifactFileStore.Session session = store.open()) {
            for (String name : List.of("../x.txt", "a/b.txt", "..", ".hidden.txt", "x.TXT", "x", "", "x.txt/", "x y.txt",
                    "text-" + "a".repeat(64) + ".tmp.", "\u0000.txt")) {
                assertEquals(ArtifactStoreException.Reason.UNAVAILABLE,
                        reason(() -> session.put("extracted_text", name, TEXT)), name);
            }
            for (String directory : List.of("../x", "A", "a/b", "", ".", "..", "x-y", "9x")) {
                assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> session.put(directory, NAME, TEXT)),
                        directory);
            }
        }
        assertFalse(Files.exists(root.getParent().resolve("x.txt")));
        assertFalse(Files.exists(root.resolve("extracted_text")));
    }

    @Test
    void aDirectoryThatIsAFileOrASymlinkIsUnusable() throws Exception {
        Files.writeString(root.resolve("extracted_text"), "not a directory");
        try (ArtifactFileStore.Session session = store.open()) {
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> session.put("extracted_text", NAME, TEXT)));
        }
        Files.delete(root.resolve("extracted_text"));
        Path elsewhere = Files.createDirectory(temp.toRealPath().resolve("elsewhere"));
        Files.createSymbolicLink(root.resolve("extracted_text"), elsewhere);
        try (ArtifactFileStore.Session session = store.open()) {
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> session.put("extracted_text", NAME, TEXT)));
        }
        try (Stream<Path> entries = Files.list(elsewhere)) {
            assertEquals(0, entries.count());
        }
    }

    @Test
    void discardRemovesOnlyAFileThisSessionCreatedAndStillIntact() throws Exception {
        Path stored = root.resolve("extracted_text").resolve(NAME);
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile created = session.put("extracted_text", NAME, TEXT);
            assertTrue(session.discard(created));
            assertFalse(Files.exists(stored));
            assertFalse(session.discard(created));

            ArtifactFileStore.StoredFile changed = session.put("extracted_text", NAME, TEXT);
            Files.write(stored, "someone else".getBytes(StandardCharsets.UTF_8));
            assertFalse(session.discard(changed));
        }
        assertEquals("someone else", Files.readString(stored));
    }

    @Test
    void aStaleTemporaryFileOfTheSameNameIsRemovedByTheNextWrite() throws Exception {
        Path directory = Files.createDirectory(root.resolve("extracted_text"));
        Files.setPosixFilePermissions(directory, OWNER_DIRECTORY);
        Path stale = Files.write(directory.resolve("." + NAME + ".deadbeefdeadbeef.tmp"), new byte[] {1, 2, 3});
        Files.setPosixFilePermissions(stale, OWNER_FILE);
        Path unrelated = Files.write(directory.resolve(".other.deadbeef.tmp"), new byte[] {4});
        Files.setPosixFilePermissions(unrelated, OWNER_FILE);
        try (ArtifactFileStore.Session session = store.open()) {
            session.put("extracted_text", NAME, TEXT);
        }
        assertFalse(Files.exists(stale));
        assertTrue(Files.exists(unrelated));
    }

    @Test
    void theOperatorLockIsExclusiveOwnerOnlyAndReleasedOnClose() throws Exception {
        ArtifactFileStore.Session first = store.open();
        try {
            assertEquals(ArtifactStoreException.Reason.BUSY, reason(store::open));
            assertPermissions(root.resolve(ArtifactFileStore.LOCK_FILE), OWNER_FILE);
        } finally {
            first.close();
        }
        try (ArtifactFileStore.Session second = store.open()) {
            assertNotNull(second);
        }
    }

    @Test
    void aLockFileThatIsNotOwnerOnlyOrIsASymlinkIsRefused() throws Exception {
        Path lock = Files.createFile(root.resolve(ArtifactFileStore.LOCK_FILE));
        Files.setPosixFilePermissions(lock, PosixFilePermissions.fromString("rw-r--r--"));
        assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(store::open));
        Files.delete(lock);

        Path target = Files.createFile(temp.toRealPath().resolve("elsewhere.lock"));
        Files.createSymbolicLink(lock, target);
        assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(store::open));
    }

    @Test
    void exceptionsCarryNoPathAndNoContent() throws Exception {
        Path directory = Files.createDirectory(root.resolve("extracted_text"));
        Files.setPosixFilePermissions(directory, OWNER_DIRECTORY);
        Path stored = Files.write(directory.resolve(NAME), "tampered".getBytes(StandardCharsets.UTF_8));
        Files.setPosixFilePermissions(stored, OWNER_FILE);
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactStoreException conflict = assertThrows(ArtifactStoreException.class,
                    () -> session.put("extracted_text", NAME, TEXT));
            assertFalse(String.valueOf(conflict.getMessage()).contains(root.toString()));
            assertFalse(String.valueOf(conflict.detail()).contains(root.toString()));
        }
        ArtifactStoreException unusable = assertThrows(ArtifactStoreException.class,
                () -> ArtifactFileStore.at(root.resolve("missing")));
        assertFalse(String.valueOf(unusable.getMessage()).contains(root.toString()));
        assertFalse(String.valueOf(unusable.detail()).contains(root.toString()));
    }

    @Test
    void readsBackExactlyWhatTheRegistryDescribes() throws Exception {
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile file = session.put("extracted_text", NAME, TEXT);

            assertArrayEquals(TEXT, session.read(file.uri(), file.sha256(), file.bytes()));
            assertArrayEquals(new byte[0], session.read(session.put("extracted_text", "empty-1.txt", new byte[0]).uri(),
                    sha256(new byte[0]), 0));
        }
    }

    @Test
    void aFileThatDisagreesWithItsRegistryRowIsAConflictAndNeverReturned() throws Exception {
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile file = session.put("extracted_text", NAME, TEXT);
            Path stored = root.resolve("extracted_text").resolve(NAME);

            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.read(file.uri(), file.sha256(), file.bytes() + 1)));
            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.read(file.uri(), file.sha256(), file.bytes() - 1)));
            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.read(file.uri(), "0".repeat(64), file.bytes())));
            assertEquals(ArtifactStoreException.Reason.CONFLICT,
                    reason(() -> session.read("artifact-root:extracted_text/missing-1.txt", file.sha256(), file.bytes())));
            assertEquals(ArtifactStoreException.Reason.CONFLICT,
                    reason(() -> session.read("artifact-root:missing_dir/" + NAME, file.sha256(), file.bytes())));

            byte[] other = TEXT.clone();
            other[0] ^= 1;
            Files.write(stored, other);
            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.read(file.uri(), file.sha256(), file.bytes())),
                    "the same size with other bytes must not be returned");

            Files.delete(stored);
            Path target = Files.write(root.resolve("extracted_text").resolve("target-1.txt"), TEXT);
            Files.setPosixFilePermissions(target, OWNER_FILE);
            Files.createSymbolicLink(stored, target);
            assertEquals(ArtifactStoreException.Reason.CONFLICT, reason(() -> session.read(file.uri(), file.sha256(), file.bytes())),
                    "a symbolic link is not a stored file");
        }
    }

    @Test
    void anInsecureEntryOrAMalformedUriIsUnavailableNotReadable() throws Exception {
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile file = session.put("extracted_text", NAME, TEXT);
            Path stored = root.resolve("extracted_text").resolve(NAME);

            for (String uri : List.of("extracted_text/" + NAME, "/etc/passwd", "artifact-root:" + NAME,
                    "artifact-root:extracted_text/../" + NAME, "artifact-root:extracted_text/sub/" + NAME,
                    "artifact-root:Extracted/" + NAME, "artifact-root:extracted_text/.hidden.txt")) {
                assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> session.read(uri, file.sha256(), file.bytes())), uri);
            }
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE,
                    reason(() -> session.read(file.uri(), "ABC", file.bytes())));
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE,
                    reason(() -> session.read(file.uri(), file.sha256(), ArtifactFileStore.MAX_READ_BYTES + 1)));
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> session.read(file.uri(), file.sha256(), -1)));

            Files.setPosixFilePermissions(stored, PosixFilePermissions.fromString("rw-r--r--"));
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> session.read(file.uri(), file.sha256(), file.bytes())));
            Files.setPosixFilePermissions(stored, OWNER_FILE);
            Files.setPosixFilePermissions(root.resolve("extracted_text"), PosixFilePermissions.fromString("rwxr-xr-x"));
            assertEquals(ArtifactStoreException.Reason.UNAVAILABLE, reason(() -> session.read(file.uri(), file.sha256(), file.bytes())));
            Files.setPosixFilePermissions(root.resolve("extracted_text"), OWNER_DIRECTORY);
            assertArrayEquals(TEXT, session.read(file.uri(), file.sha256(), file.bytes()));
        }
    }
}
