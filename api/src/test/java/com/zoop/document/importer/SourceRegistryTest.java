package com.zoop.document.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.PosixFilePermission;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.function.Consumer;
import java.util.stream.Stream;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * The S2-1 source registry reader and decision rule at parity with {@code ingestion_contracts.Registry} and
 * {@code Authority.check}: the shape of the operator's actual synthetic registry (the smoke fixtures' {@code source_entry})
 * is accepted, every closed-shape or bound violation refuses the whole registry, and the fixed read/store/quote-display
 * decision is made from the registry as read and the authority clock only.
 */
class SourceRegistryTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final Instant NOW = Instant.parse("2026-10-20T05:00:00Z");
    private static final String SOURCE = "synthetic-source";

    /** One source exactly as the smoke fixtures write it (authored files, one scope, a known enabled grant). */
    private static ObjectNode entry(String sourceId, String grantId, String revision) {
        ObjectNode source = JSON.createObjectNode();
        source.put("sourceId", sourceId);
        source.put("adapter", "authored-files");
        source.put("inputRoot", "/srv/zoop/inputs");
        source.putArray("allowedHosts").add("example.invalid");
        ObjectNode scope = source.putArray("scopes").addObject();
        scope.put("scopeId", "body");
        scope.put("selection", "authored source slice");
        scope.putNull("initialCursor");
        scope.putNull("articleXPath");
        scope.putArray("timestampLimitations").add("authored fixtures; no real provider late-registration guarantee");
        ObjectNode grant = source.putObject("grant");
        grant.put("grantId", grantId);
        grant.put("revision", revision);
        grant.put("sourceId", sourceId);
        grant.put("enabled", true);
        grant.put("rights", "known");
        grant.putArray("allowedOperations").add("read").add("store").add("quote-display");
        grant.putArray("recipients");
        grant.putArray("purposes");
        grant.putArray("evidence").add("operator-owned authored synthetic fixtures");
        grant.putNull("expiresAt");
        return source;
    }

    private static ObjectNode registry(ObjectNode... sources) {
        ObjectNode root = JSON.createObjectNode();
        root.put("schemaVersion", "zoop-ingestion-s2-1");
        root.put("revision", "registry-1");
        ArrayNode array = root.putArray("sources");
        for (ObjectNode source : sources) {
            array.add(source);
        }
        return root;
    }

    private static ObjectNode valid() {
        return registry(entry(SOURCE, "grant-1", "rev-1"));
    }

    private static ObjectNode source(ObjectNode root) {
        return (ObjectNode) root.get("sources").get(0);
    }

    private static ObjectNode grant(ObjectNode root) {
        return (ObjectNode) source(root).get("grant");
    }

    private static ObjectNode scope(ObjectNode root) {
        return (ObjectNode) source(root).get("scopes").get(0);
    }

    private static byte[] bytes(ObjectNode node) {
        return JSON.writeValueAsBytes(node);
    }

    private static SourceRegistry parse(ObjectNode root) {
        return SourceRegistry.parse(bytes(root));
    }

    private static SourceRegistry with(Consumer<ObjectNode> grantChange) {
        ObjectNode root = valid();
        grantChange.accept(grant(root));
        return parse(root);
    }

    private static String denial(SourceRegistry registry) {
        return registry.denial(SOURCE, "grant-1", "rev-1", NOW);
    }

    private static void assertInvalid(byte[] data) {
        SourceRegistry.Invalid error = assertThrows(SourceRegistry.Invalid.class, () -> SourceRegistry.parse(data));
        assertEquals("source_registry_invalid", error.code());
        assertEquals("source_registry_invalid", error.getMessage());
        assertNull(error.getCause());
    }

    private static void assertInvalid(Consumer<ObjectNode> mutation) {
        ObjectNode root = valid();
        mutation.accept(root);
        assertInvalid(bytes(root));
    }

    @Test
    void theSyntheticRegistryAllowsExactlyItsCurrentGrantAtTheFixedOperations() {
        SourceRegistry registry = parse(valid());

        assertNull(denial(registry));
        assertEquals(Set.of("read", "store", "quote-display"), SourceRegistry.OPERATIONS);
    }

    @Test
    void theCollectedHttpFixtureShapeIsAccepted() {
        ObjectNode root = valid();
        source(root).put("adapter", "collected-http");
        ((ArrayNode) source(root).get("allowedHosts")).removeAll().add("127.0.0.1");
        ((ArrayNode) scope(root).get("timestampLimitations")).removeAll().add("one-off explicit URL list");
        scope(root).put("initialCursor", "c0").put("articleXPath", "//article");
        ((ArrayNode) grant(root).get("allowedOperations")).add("model-send");
        grant(root).put("expiresAt", "2030-01-01T00:00:00+09:00");

        assertNull(denial(parse(root)));
    }

    @Test
    void supportedPythonIsoExpiriesKeepTheirExistingPermission() {
        for (String expiry : List.of("2030-01-01T00:00Z", "2030-01-01T00:00:00Z",
                "2030-01-01t00:00:00Z", "2030-01-01T00:00:00.123456000Z",
                "2030-01-01T00:00:00.123456Z", "2030-01-01T00:00:00+09:00",
                "2030-01-01T00:00:00+09:00:01")) {
            assertNull(denial(with(grant -> grant.put("expiresAt", expiry))), expiry);
        }
    }

    @Test
    void modelSendPurposesAndRecipientsAreNeverPartOfTheRule() {
        assertNull(denial(with(grant -> ((ArrayNode) grant.get("allowedOperations")).add("model-send"))));
        assertNull(denial(with(grant -> {
            grant.putArray("recipients").add("openai-compatible:r1");
            grant.putArray("purposes").add("anything-at-all");
        })));
    }

    @Test
    void aSourceThatIsNotListedOrNotNamedIsDeniedWithoutTouchingAnotherSourcesGrant() {
        ObjectNode other = entry("other-source", "grant-2", "rev-9");
        ((ObjectNode) other.get("grant")).put("enabled", false);
        SourceRegistry registry = parsed(entry(SOURCE, "grant-1", "rev-1"), other);

        assertNull(denial(registry));
        assertEquals("source_unknown", registry.denial("absent-source", "grant-1", "rev-1", NOW));
        assertEquals("source_unknown", registry.denial(null, "grant-1", "rev-1", NOW));
        assertEquals("source_unknown", registry.denial(SOURCE.toUpperCase(), "grant-1", "rev-1", NOW));
        // The other source's own grant is disabled; this source's pin may not borrow or leak into it.
        assertEquals("source_rights_unknown_or_denied", registry.denial("other-source", "grant-2", "rev-9", NOW));
        assertEquals("grant_revision_or_source_changed", registry.denial("other-source", "grant-1", "rev-1", NOW));
        assertEquals("grant_revision_or_source_changed", registry.denial(SOURCE, "grant-2", "rev-9", NOW));
    }

    private static SourceRegistry parsed(ObjectNode... sources) {
        return parse(registry(sources));
    }

    @Test
    void theGrantIdAndTheRevisionMustMatchTheCurrentOnesExactly() {
        SourceRegistry registry = parse(valid());

        for (String[] pin : new String[][] {{"grant-2", "rev-1"}, {"grant-1", "rev-2"}, {"Grant-1", "rev-1"},
                {"grant-1", "REV-1"}, {"grant-1 ", "rev-1"}, {"", ""}, {null, "rev-1"}, {"grant-1", null}}) {
            assertEquals("grant_revision_or_source_changed", registry.denial(SOURCE, pin[0], pin[1], NOW), Arrays.toString(pin));
        }
        // A newer revision in the registry denies what was imported under the older one, and the reverse.
        SourceRegistry bumped = with(grant -> grant.put("revision", "rev-2"));
        assertEquals("grant_revision_or_source_changed", denial(bumped));
        assertNull(bumped.denial(SOURCE, "grant-1", "rev-2", NOW));
    }

    @Test
    void aDisabledOrNotKnownGrantIsDeniedWhateverElseItSays() {
        assertEquals("source_rights_unknown_or_denied", denial(with(grant -> grant.put("enabled", false))));
        assertEquals("source_rights_unknown_or_denied", denial(with(grant -> grant.put("rights", "unknown"))));
        assertEquals("source_rights_unknown_or_denied", denial(with(grant -> grant.put("rights", "denied"))));
    }

    @Test
    void evidenceMustHoldAtLeastOneNonBlankEntry() {
        for (String blank : List.of("", " ", "\t\n", "\u00a0", "\u2003", "\u200b", "\ufeff", "\u0000", " \u00a0\u200b\u2028 ")) {
            assertEquals("source_rights_unknown_or_denied",
                    denial(with(grant -> grant.putArray("evidence").add(blank))), "blank evidence: " + blank.length());
        }
        assertEquals("source_rights_unknown_or_denied", denial(with(grant -> grant.putArray("evidence"))));
        assertEquals("source_rights_unknown_or_denied",
                denial(with(grant -> grant.putArray("evidence").add(" ").add("\u200b"))));
        assertNull(denial(with(grant -> grant.putArray("evidence").add(" ").add("licence 7"))));
        assertNull(denial(with(grant -> grant.putArray("evidence").add("\u200bx"))));
    }

    @Test
    void everyOneOfReadStoreAndQuoteDisplayIsRequired() {
        for (String missing : List.of("read", "store", "quote-display")) {
            SourceRegistry registry = with(grant -> {
                ArrayNode operations = grant.putArray("allowedOperations");
                List.of("read", "store", "quote-display", "model-send").stream().filter(op -> !op.equals(missing))
                        .forEach(operations::add);
            });
            assertEquals("source_operation_denied", denial(registry), missing);
        }
        assertEquals("source_operation_denied", denial(with(grant -> grant.putArray("allowedOperations"))));
        assertEquals("source_operation_denied",
                denial(with(grant -> grant.putArray("allowedOperations").add("model-send"))));
        assertNull(denial(with(grant -> grant.putArray("allowedOperations").add("quote-display").add("store").add("read")
                .add("read"))));
    }

    @Test
    void expiryIsReadAtTheAuthorityClockAndEndsAtTheInstantItNames() {
        assertEquals("source_grant_expired", denial(with(grant -> grant.put("expiresAt", "2026-10-20T05:00:00Z"))));
        assertEquals("source_grant_expired", denial(with(grant -> grant.put("expiresAt", "2026-10-20T14:00:00+09:00"))));
        assertEquals("source_grant_expired", denial(with(grant -> grant.put("expiresAt", "2020-01-01T00:00:00Z"))));
        assertNull(denial(with(grant -> grant.put("expiresAt", "2026-10-20T05:00:01Z"))));
        assertNull(denial(with(grant -> grant.put("expiresAt", "2026-10-20T14:00:01+09:00"))));
        assertNull(denial(with(grant -> grant.put("expiresAt", "9999-12-31T23:59:59Z"))));

        SourceRegistry expiring = with(grant -> grant.put("expiresAt", "2026-10-20T05:00:01Z"));
        assertNull(expiring.denial(SOURCE, "grant-1", "rev-1", NOW));
        assertEquals("source_grant_expired", expiring.denial(SOURCE, "grant-1", "rev-1", NOW.plusSeconds(1)));
        assertEquals("source_grant_expired", expiring.denial(SOURCE, "grant-1", "rev-1", NOW.plusSeconds(3600)));
    }

    @Test
    void theDenialsComeInAFixedOrder() {
        SourceRegistry broken = with(grant -> {
            grant.put("enabled", false);
            grant.put("expiresAt", "2020-01-01T00:00:00Z");
            grant.putArray("allowedOperations");
        });
        assertEquals("source_unknown", broken.denial("absent", "grant-1", "rev-1", NOW));
        assertEquals("grant_revision_or_source_changed", broken.denial(SOURCE, "x", "rev-1", NOW));
        assertEquals("source_rights_unknown_or_denied", denial(broken));

        SourceRegistry expiredWithoutOperations = with(grant -> {
            grant.put("expiresAt", "2020-01-01T00:00:00Z");
            grant.putArray("allowedOperations");
        });
        assertEquals("source_grant_expired", denial(expiredWithoutOperations));
    }

    @Test
    void emptySourceListsAndTheDocumentedMaximaAreValid() {
        assertEquals("source_unknown", parsed().denial(SOURCE, "grant-1", "rev-1", NOW));

        ObjectNode[] sources = new ObjectNode[100];
        for (int index = 0; index < sources.length; index++) {
            sources[index] = entry("source-" + index, "grant-" + index, "rev");
        }
        assertNull(parsed(sources).denial("source-99", "grant-99", "rev", NOW));

        ObjectNode root = valid();
        ArrayNode hosts = ((ArrayNode) source(root).get("allowedHosts")).removeAll();
        for (int index = 0; index < 100; index++) {
            hosts.add("host-" + index + ".example");
        }
        ArrayNode scopes = ((ArrayNode) source(root).get("scopes")).removeAll();
        for (int index = 0; index < 100; index++) {
            ObjectNode scope = scopes.addObject();
            scope.put("scopeId", "scope-" + index);
            scope.put("selection", "\uD83D\uDE00".repeat(2_000));
            scope.putNull("initialCursor");
            scope.putNull("articleXPath");
            ArrayNode limitations = scope.putArray("timestampLimitations");
            for (int limit = 0; limit < 20; limit++) {
                limitations.add("limitation " + limit);
            }
        }
        assertNull(denial(parse(root)));
        // The empty host and a non-ASCII lower-case host pass Python's rule, so they pass here.
        ((ArrayNode) source(root).get("allowedHosts")).removeAll().add("").add("münchen.example");
        assertNull(denial(parse(root)));
    }

    @Test
    void theShapeIsClosedAtEveryLevel() {
        assertInvalid(root -> root.put("extra", 1));
        assertInvalid(root -> root.remove("revision"));
        assertInvalid(root -> root.remove("sources"));
        assertInvalid(root -> root.remove("schemaVersion"));
        assertInvalid(root -> source(root).put("extra", 1));
        for (String key : List.of("sourceId", "adapter", "inputRoot", "allowedHosts", "scopes", "grant")) {
            assertInvalid(root -> source(root).remove(key));
        }
        assertInvalid(root -> scope(root).put("extra", 1));
        for (String key : List.of("scopeId", "selection", "initialCursor", "articleXPath", "timestampLimitations")) {
            assertInvalid(root -> scope(root).remove(key));
        }
        assertInvalid(root -> grant(root).put("extra", 1));
        for (String key : List.of("grantId", "revision", "sourceId", "enabled", "rights", "allowedOperations", "recipients",
                "purposes", "evidence", "expiresAt")) {
            assertInvalid(root -> grant(root).remove(key));
        }
    }

    @Test
    void valuesOfTheWrongTypeOrOutsideTheirEnumerationRefuseTheWholeRegistry() {
        assertInvalid(root -> root.put("schemaVersion", "zoop-ingestion-s2-2"));
        assertInvalid(root -> root.put("schemaVersion", "zoop-ai-s1-1"));
        assertInvalid(root -> root.put("revision", ""));
        assertInvalid(root -> root.put("revision", 1));
        assertInvalid(root -> root.put("sources", "none"));
        assertInvalid(root -> source(root).put("adapter", "live-http"));
        assertInvalid(root -> source(root).put("sourceId", ""));
        assertInvalid(root -> grant(root).put("sourceId", ""));
        assertInvalid(root -> grant(root).put("grantId", ""));
        assertInvalid(root -> grant(root).put("revision", ""));
        assertInvalid(root -> grant(root).put("enabled", "true"));
        assertInvalid(root -> grant(root).put("enabled", 1));
        assertInvalid(root -> grant(root).putNull("enabled"));
        assertInvalid(root -> grant(root).put("rights", "Known"));
        assertInvalid(root -> grant(root).put("rights", "granted"));
        assertInvalid(root -> grant(root).putArray("allowedOperations").add("read").add("export"));
        assertInvalid(root -> grant(root).putArray("allowedOperations").add(1));
        assertInvalid(root -> grant(root).put("recipients", "none"));
        assertInvalid(root -> grant(root).putArray("purposes").add(1));
        assertInvalid(root -> grant(root).putArray("evidence").add(JSON.createObjectNode()));
        assertInvalid(root -> grant(root).put("evidence", "licence"));
        assertInvalid(root -> scope(root).put("selection", 5));
        assertInvalid(root -> scope(root).put("initialCursor", 5));
        assertInvalid(root -> scope(root).put("articleXPath", false));
        assertInvalid(root -> scope(root).put("scopeId", ""));
    }

    @Test
    void sourceBindingScopesHostsAndTheInputRootAreEnforced() {
        assertInvalid(root -> grant(root).put("sourceId", "another-source"));
        assertInvalid(root -> grant(root).put("sourceId", SOURCE.toUpperCase()));
        assertInvalid(root -> ((ArrayNode) root.get("sources")).add(entry(SOURCE, "grant-2", "rev-2")));
        assertInvalid(root -> ((ArrayNode) source(root).get("scopes")).add(scope(root).deepCopy()));
        assertInvalid(root -> ((ArrayNode) source(root).get("scopes")).removeAll());
        assertInvalid(root -> source(root).put("scopes", "body"));
        assertInvalid(root -> source(root).put("inputRoot", ""));
        assertInvalid(root -> source(root).put("inputRoot", "inputs"));
        assertInvalid(root -> source(root).put("inputRoot", "./inputs"));
        assertInvalid(root -> source(root).put("inputRoot", "file:///inputs"));
        assertInvalid(root -> ((ArrayNode) source(root).get("allowedHosts")).removeAll());
        for (String host : List.of("Example.invalid", "example.invalid.", "example.invalid..", "https://example.invalid",
                "example.invalid/x", "example.invalid:443", "user@example.invalid", "*.example.invalid", "example invalid",
                "EXAMPLE.invalid", "MÜNCHEN.example")) {
            assertInvalid(root -> ((ArrayNode) source(root).get("allowedHosts")).add(host));
        }
        assertInvalid(root -> source(root).put("allowedHosts", "example.invalid"));
    }

    @Test
    void listAndLengthBoundsRefuseTheWholeRegistry() {
        assertInvalid(root -> {
            ArrayNode sources = ((ArrayNode) root.get("sources")).removeAll();
            for (int index = 0; index < 101; index++) {
                sources.add(entry("source-" + index, "grant-" + index, "rev"));
            }
        });
        assertInvalid(root -> {
            ArrayNode hosts = ((ArrayNode) source(root).get("allowedHosts")).removeAll();
            for (int index = 0; index < 101; index++) {
                hosts.add("host-" + index + ".example");
            }
        });
        assertInvalid(root -> {
            ArrayNode scopes = ((ArrayNode) source(root).get("scopes")).removeAll();
            for (int index = 0; index < 101; index++) {
                ObjectNode extra = scope(valid());
                extra.put("scopeId", "scope-" + index);
                scopes.add(extra);
            }
        });
        assertInvalid(root -> scope(root).put("selection", "x".repeat(2_001)));
        assertInvalid(root -> scope(root).put("selection", "\uD83D\uDE00".repeat(2_000) + "x"));
        assertInvalid(root -> scope(root).put("selection", ""));
        assertInvalid(root -> scope(root).putArray("timestampLimitations"));
        assertInvalid(root -> {
            ArrayNode limitations = scope(root).putArray("timestampLimitations");
            for (int index = 0; index < 21; index++) {
                limitations.add("limitation " + index);
            }
        });
        assertInvalid(root -> scope(root).putArray("timestampLimitations").add(1));
    }

    @Test
    void anExpiryTheStrictTimestampReaderCannotReadRefusesTheWholeRegistry() {
        for (String expiry : List.of("", "tomorrow", "2026-10-20", "2026-10-20T05:00:00", "2026-10-20 05:00:00+00:00",
                "20261020T050000Z", "2026-10-20T05:00:00.1234567Z", "2026-13-20T05:00:00Z", "2026-10-20T25:00:00Z",
                "0000-01-01T00:00:00Z", "+10000-01-01T00:00:00Z")) {
            assertInvalid(root -> grant(root).put("expiresAt", expiry));
        }
        assertInvalid(root -> grant(root).put("expiresAt", 1_800_000_000));
        // One bad grant refuses the registry for every source, as a Python validation failure does.
        assertInvalid(root -> {
            ObjectNode other = entry("other-source", "grant-2", "rev-2");
            ((ObjectNode) other.get("grant")).put("expiresAt", "soon");
            ((ArrayNode) root.get("sources")).add(other);
        });
    }

    @Test
    void aLowercaseUtcMarkerRefusesTheWholeRegistryEvenWhenTheSourceIsUnrelated() {
        assertInvalid(root -> grant(root).put("expiresAt", "2030-01-01T00:00:00z"));
        assertInvalid(root -> {
            ObjectNode other = entry("other-source", "grant-2", "rev-2");
            ((ObjectNode) other.get("grant")).put("expiresAt", "2030-01-01T00:00:00z");
            ((ArrayNode) root.get("sources")).add(other);
        });
    }

    @Test
    void aDuplicateKeyTrailingTokensMalformedTextOrUnpairedSurrogateIsRefused() throws Exception {
        String valid = new String(bytes(valid()), StandardCharsets.UTF_8);
        assertInvalid(valid.replace("\"revision\":\"registry-1\"", "\"revision\":\"registry-1\",\"revision\":\"registry-2\"")
                .getBytes(StandardCharsets.UTF_8));
        assertInvalid(valid.replace("\"enabled\":true", "\"enabled\":false,\"enabled\":true").getBytes(StandardCharsets.UTF_8));
        assertInvalid((valid + " {}").getBytes(StandardCharsets.UTF_8));
        assertInvalid((valid + "x").getBytes(StandardCharsets.UTF_8));
        assertInvalid(("[" + valid + "]").getBytes(StandardCharsets.UTF_8));
        assertInvalid("null".getBytes(StandardCharsets.UTF_8));
        assertInvalid(new byte[0]);
        assertInvalid("{".getBytes(StandardCharsets.UTF_8));
        assertInvalid(valid.replace("authored source slice", "authored \\ud800 slice").getBytes(StandardCharsets.UTF_8));
        assertInvalid(valid.replace("operator-owned authored synthetic fixtures", "\\udc00").getBytes(StandardCharsets.UTF_8));
        // Input that is not UTF-8 at all.
        byte[] latin = valid.replace("authored source slice", "caf\u00e9").getBytes(StandardCharsets.ISO_8859_1);
        assertInvalid(latin);
        // A well-formed escape pair, an astral and a plain Hangul character are all fine.
        assertNull(SourceRegistry.parse(valid.replace("authored source slice", "\\ud83d\\ude00 \uD83D\uDE00 \uac00")
                .getBytes(StandardCharsets.UTF_8)).denial(SOURCE, "grant-1", "rev-1", NOW));
    }

    @Test
    void aFailureNamesNothingFromTheRegistry() {
        ObjectNode root = valid();
        grant(root).put("rights", "SECRET-RIGHTS").putArray("evidence").add("SECRET-EVIDENCE");
        source(root).put("inputRoot", "/SECRET/ROOT");
        SourceRegistry.Invalid error = assertThrows(SourceRegistry.Invalid.class, () -> parse(root));

        assertEquals("source_registry_invalid", error.getMessage());
        assertFalse(error.toString().contains("SECRET"));
        assertEquals(0, error.getStackTrace().length);
    }

    // ------------------------------------------------------------------------------------------------- the file ------

    private static Path registryFile(Path directory) throws IOException {
        Path file = directory.resolve("sources.json");
        Files.write(file, bytes(valid()));
        return file;
    }

    @Test
    void aRegularFileIsReadFreshOnEveryCallAndNeverTouched(@TempDir Path temp) throws Exception {
        Path root = temp.toRealPath();
        Path file = registryFile(root);
        byte[] before = Files.readAllBytes(file);
        List<String> listing = names(root);
        Instant modified = Files.getLastModifiedTime(file).toInstant();

        assertNull(denial(SourceRegistry.read(file)));
        assertNull(denial(SourceRegistry.read(file)));

        assertArrayEquals(before, Files.readAllBytes(file));
        assertEquals(listing, names(root));
        assertEquals(modified, Files.getLastModifiedTime(file).toInstant());

        // Rewriting the operator file is what withdraws a right: the next read sees it, no reader holds a copy.
        ObjectNode disabled = valid();
        grant(disabled).put("enabled", false);
        Files.write(file, bytes(disabled));
        assertEquals("source_rights_unknown_or_denied", denial(SourceRegistry.read(file)));
        Files.delete(file);
        assertEquals("source_registry_unreadable", assertThrows(SourceRegistry.Invalid.class, () -> SourceRegistry.read(file)).code());
    }

    @Test
    void anAtomicSameDirectoryRegularFileReplacementChangesTheNextRead(@TempDir Path temp) throws Exception {
        Path root = temp.toRealPath();
        Path file = registryFile(root);
        assertNull(denial(SourceRegistry.read(file)));

        ObjectNode disabled = valid();
        grant(disabled).put("enabled", false);
        Path replacement = root.resolve("next.json");
        Files.write(replacement, bytes(disabled));
        Files.move(replacement, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);

        assertEquals("source_rights_unknown_or_denied", denial(SourceRegistry.read(file)));
    }

    @Test
    void aGroupOrWorldWritableOperatorRegistryIsUnreadableOnPosix(@TempDir Path temp) throws Exception {
        Path root = temp.toRealPath();
        Assumptions.assumeTrue(Files.getFileStore(root).supportsFileAttributeView("posix"));
        Path file = registryFile(root);
        for (PosixFilePermission extraWriter : List.of(PosixFilePermission.GROUP_WRITE, PosixFilePermission.OTHERS_WRITE)) {
            Files.setPosixFilePermissions(file, Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE,
                    extraWriter));
            SourceRegistry.Invalid error = assertThrows(SourceRegistry.Invalid.class, () -> SourceRegistry.read(file));
            assertEquals("source_registry_unreadable", error.code(), extraWriter.toString());
            assertFalse(error.getMessage().contains(root.toString()));
        }
    }

    private static List<String> names(Path directory) throws IOException {
        try (Stream<Path> entries = Files.list(directory)) {
            return entries.map(path -> path.getFileName().toString()).sorted().toList();
        }
    }

    @Test
    void aMissingPathADirectoryOrAnythingNotARegularFileIsUnreadable(@TempDir Path temp) throws Exception {
        Path root = temp.toRealPath();
        Path directory = Files.createDirectory(root.resolve("a-directory"));

        Files.write(root.resolve("sources.json"), bytes(valid()));
        for (Path path : List.of(root.resolve("absent.json"), directory, root.resolve("absent/dir/sources.json"),
                root.resolve("sources.json/inside"))) {
            SourceRegistry.Invalid error = assertThrows(SourceRegistry.Invalid.class, () -> SourceRegistry.read(path));
            assertEquals("source_registry_unreadable", error.code(), path.toString());
            assertFalse(error.getMessage().contains(root.toString()));
        }
    }

    @Test
    void aSymbolicLinkAnywhereInThePathIsRefused(@TempDir Path temp) throws Exception {
        Path root = temp.toRealPath();
        Path real = registryFile(Files.createDirectory(root.resolve("real")));
        Path leafLink = Files.createSymbolicLink(root.resolve("leaf-link.json"), real);
        Path directoryLink = Files.createSymbolicLink(root.resolve("dir-link"), real.getParent());
        Path dangling = Files.createSymbolicLink(root.resolve("dangling.json"), root.resolve("nowhere.json"));

        assertNull(denial(SourceRegistry.read(real)));
        for (Path path : List.of(leafLink, directoryLink.resolve("sources.json"), dangling)) {
            assertEquals("source_registry_unreadable",
                    assertThrows(SourceRegistry.Invalid.class, () -> SourceRegistry.read(path)).code(), path.toString());
        }
        // `..` is resolved lexically before the walk, exactly as Python's abspath does.
        assertNull(denial(SourceRegistry.read(root.resolve("real/../real/sources.json"))));
    }

    @Test
    void theFileBoundIsInclusiveAtTwoMillionBytes(@TempDir Path temp) throws Exception {
        Path root = temp.toRealPath();
        byte[] json = bytes(valid());
        byte[] exact = new byte[SourceRegistry.MAX_BYTES];
        Arrays.fill(exact, (byte) ' ');
        System.arraycopy(json, 0, exact, 0, json.length);
        Path file = root.resolve("exact.json");
        Files.write(file, exact);
        assertNull(denial(SourceRegistry.read(file)));

        byte[] over = Arrays.copyOf(exact, exact.length + 1);
        over[exact.length] = ' ';
        Path large = root.resolve("large.json");
        Files.write(large, over);
        assertEquals("source_registry_too_large", assertThrows(SourceRegistry.Invalid.class, () -> SourceRegistry.read(large)).code());
        assertEquals("source_registry_too_large", assertThrows(SourceRegistry.Invalid.class, () -> SourceRegistry.parse(over)).code());
        assertEquals(SourceRegistry.MAX_BYTES + 1, Files.size(large));
    }
    @Test
    void exactTupleRoutesKeepBothGrantsCurrentAndRevocationLocal(@TempDir Path temp) throws Exception {
        Path root = temp.toRealPath();
        Path left = root.resolve("left.json");
        Path right = root.resolve("right.json");
        ObjectNode first = registry(entry(SOURCE, "old-grant", "r1"));
        ObjectNode second = registry(entry(SOURCE, "new-grant", "r2"));
        Files.write(left, bytes(first));
        Files.write(right, bytes(second));
        ObjectNode wrapper = JSON.createObjectNode().put("schemaVersion", SourceRegistry.AUTHORITY_SET_SCHEMA);
        ArrayNode routes = wrapper.putArray("authorities");
        routes.addObject().put("sourceId", SOURCE).put("grantId", "old-grant").put("revision", "r1").put("sources", left.toString());
        routes.addObject().put("sourceId", SOURCE).put("grantId", "new-grant").put("revision", "r2").put("sources", right.toString());
        Path file = root.resolve("authorities.json");
        Files.write(file, bytes(wrapper));
        SourceRegistry current = SourceRegistry.read(file);
        assertNull(current.denial(SOURCE, "old-grant", "r1", NOW));
        assertNull(current.denial(SOURCE, "new-grant", "r2", NOW));
        assertEquals("source_unknown", current.denial(SOURCE, "old-grant", "r2", NOW));
        assertEquals("source_url_outside_grant", current.denialForUrl(SOURCE, "new-grant", "r2", "https://foreign.invalid/a", NOW));
        for (int revoked = 0; revoked < 2; revoked++) {
            ObjectNode leaf = revoked == 0 ? first : second;
            Path path = revoked == 0 ? left : right;
            grant(leaf).put("enabled", false);
            Files.write(path, bytes(leaf));
            assertEquals("source_rights_unknown_or_denied",
                    current.denial(SOURCE, revoked == 0 ? "old-grant" : "new-grant", revoked == 0 ? "r1" : "r2", NOW));
            assertNull(current.denial(SOURCE, revoked == 0 ? "new-grant" : "old-grant", revoked == 0 ? "r2" : "r1", NOW));
            grant(leaf).put("enabled", true);
            Files.write(path, bytes(leaf));
        }
        Files.delete(left);
        assertEquals("source_registry_unreadable",
                assertThrows(SourceRegistry.Invalid.class, () -> current.denial(SOURCE, "old-grant", "r1", NOW)).code());
        assertNull(current.denial(SOURCE, "new-grant", "r2", NOW));
        Files.write(left, bytes(wrapper));
        assertEquals("source_registry_invalid",
                assertThrows(SourceRegistry.Invalid.class, () -> current.denial(SOURCE, "old-grant", "r1", NOW)).code());
        routes.add(routes.get(1).deepCopy());
        Files.write(file, bytes(wrapper));
        assertThrows(SourceRegistry.Invalid.class, () -> SourceRegistry.read(file));
        assertThrows(SourceRegistry.Invalid.class, () -> current.denial(SOURCE, "new-grant", "r2", NOW));
    }
}
