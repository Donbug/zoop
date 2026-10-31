package com.zoop.document.importer;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.ReadableByteChannel;
import java.nio.channels.SeekableByteChannel;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.OpenOption;
import java.nio.file.Path;
import java.nio.file.SecureDirectoryStream;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFileAttributeView;
import java.nio.file.attribute.PosixFilePermission;
import java.time.Instant;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import tools.jackson.databind.JsonNode;

/**
 * Read-only current-authority reader for the operator-owned S2-1 source registry ({@code zoop-ingestion-s2-1}), ported from
 * {@code ai/pipeline/.../ingestion_contracts.py} ({@code Registry}, {@code Source}, {@code Scope}, {@code Grant} and
 * {@code Authority.check}, no Python import). It is the authority the S2-1 export checks with {@code --require-store}: the
 * rights an import was made under are frozen provenance, this file is what allows a read <em>now</em>.
 * The optional {@code zoop-source-authority-set-1} wrapper routes exact source/grant/revision tuples to local S2-1 leaves.
 * A selected leaf is read fresh for every decision; wrapper bytes remain fixed through the reader's lifetime.
 *
 * <p>The file is read fresh by every caller (nothing is cached), never written, locked or created. Under the operator-only
 * path ownership contract, symlinks and non-regular files are refused and the file is bounded to {@value #MAX_BYTES} bytes.
 * POSIX group/other-writable files are refused where that attribute view exists; privileged concurrent local replacement
 * is outside the path-check guarantee. Registry validation is at parity with the Python model or stricter, never looser:
 * closed key sets, duplicate JSON keys refused (Python keeps the last), the Python length limits, unique source and scope
 * ids, {@code grant.sourceId == sourceId}, an absolute {@code inputRoot}, exact lower-case hosts. An {@code expiresAt}
 * must first match the explicit extended ISO syntax subset accepted by Python's {@code datetime.fromisoformat}; the
 * timestamp parser then validates the calendar and offset. An unreadable expiry invalidates the whole registry, even
 * when it belongs to another source.
 *
 * <p>Only the use this app makes is decided: the fixed operations {@code read}, {@code store} and {@code quote-display}.
 * Displaying a quote sends nothing to a model, so {@code model-send}, purposes and recipients are never part of the rule (the
 * S2-1 CLI evaluates none of them). Scopes, adapters, hosts and the input root are validated but play no part in the decision.
 */
public final class SourceRegistry {
    public static final int MAX_BYTES = 2_000_000;
    /** The operations every graph evidence read needs; the same set {@code zoop-ai-ingest export --require-store} requires. */
    public static final Set<String> OPERATIONS = Set.of("read", "store", "quote-display");

    private static final Set<String> TOP = Set.of("schemaVersion", "revision", "sources");
    public static final String AUTHORITY_SET_SCHEMA = "zoop-source-authority-set-1";
    private static final Set<String> AUTHORITY_SET = Set.of("schemaVersion", "authorities");
    private static final Set<String> AUTHORITY_ROUTE = Set.of("sourceId", "grantId", "revision", "sources");
    private static final Set<String> SOURCE = Set.of("sourceId", "adapter", "inputRoot", "allowedHosts", "scopes", "grant");
    private static final Set<String> SCOPE = Set.of("scopeId", "selection", "initialCursor", "articleXPath",
            "timestampLimitations");
    private static final Set<String> GRANT = Set.of("grantId", "revision", "sourceId", "enabled", "rights", "allowedOperations",
            "recipients", "purposes", "evidence", "expiresAt");
    private static final Set<String> ADAPTERS = Set.of("authored-files", "collected-http");
    private static final Set<String> RIGHTS = Set.of("known", "unknown", "denied");
    private static final Set<String> GRANTED = Set.of("read", "store", "model-send", "quote-display");
    private static final int MAX_LIST = 100;
    private static final int MAX_SELECTION_CODE_POINTS = 2_000;
    private static final int MAX_LIMITATIONS = 20;
    private static final Set<OpenOption> READ_NOFOLLOW = Set.of(StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS);
    private static final Pattern EXPIRY = Pattern.compile(
            "[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\\.[0-9]{1,9})?)?"
                    + "(?:Z|[+-][0-9]{2}:[0-9]{2}(?::[0-9]{2})?)");

    private final Map<String, SourceGrant> grants;
    private final Map<GrantKey, Path> routes;
    private final Path routingPath;
    private final byte[] routingBytes;

    private record GrantKey(String sourceId, String grantId, String revision) {}

    private SourceRegistry(Map<String, SourceGrant> grants) {
        this.grants = grants;
        this.routes = Map.of();
        this.routingPath = null;
        this.routingBytes = null;
    }

    private SourceRegistry(Map<GrantKey, Path> routes, Path path, byte[] bytes) {
        this.grants = Map.of();
        this.routes = Map.copyOf(routes);
        this.routingPath = path;
        this.routingBytes = bytes;
    }

    /**
     * The registry was refused. The message is one of {@code source_registry_unreadable}, {@code source_registry_too_large}
     * and {@code source_registry_invalid}; it carries no path, no content and no cause.
     */
    public static final class Invalid extends RuntimeException {
        private final String code;

        Invalid(String code) {
            super(code, null, false, false);
            this.code = code;
        }

        public String code() {
            return code;
        }
    }

    /** The grant of one source as the Python {@code Grant} model reads it; recipients and purposes are not part of the rule. */
    private record SourceGrant(String grantId, String revision, boolean enabled, String rights, Set<String> operations,
            List<String> evidence, Instant expiresAt, Set<String> allowedHosts) {
    }

    /**
     * Reads and validates the whole operator-owned registry. Checks path components and leaf type/bound before opening;
     * callers must prevent untrusted local writes to the file and its parent chain. Nothing is created, changed or locked.
     */
    public static SourceRegistry read(Path path) throws Invalid {
        byte[] data = readBounded(path);
        try {
            StrictJson.Obj root = StrictJson.parseObject(data);
            if (!AUTHORITY_SET_SCHEMA.equals(root.string("schemaVersion"))) return parse(data);
            root.exactly(AUTHORITY_SET);
            wellFormed(root.node());
            Map<GrantKey, Path> routes = new HashMap<>();
            List<StrictJson.Obj> authorities = root.objects("authorities");
            if (authorities.isEmpty()) throw invalid();
            for (StrictJson.Obj entry : authorities) {
                entry.exactly(AUTHORITY_ROUTE);
                GrantKey key = new GrantKey(nonEmpty(entry.string("sourceId")), nonEmpty(entry.string("grantId")),
                        nonEmpty(entry.string("revision")));
                Path leaf = Path.of(entry.string("sources"));
                if (!leaf.isAbsolute() || !leaf.equals(leaf.normalize()) || routes.put(key, leaf) != null) throw invalid();
            }
            return new SourceRegistry(routes, path, data);
        } catch (StrictJson.Malformed | java.nio.file.InvalidPathException error) {
            throw invalid();
        }
    }

    static SourceRegistry parse(byte[] data) {
        if (data.length > MAX_BYTES) {
            throw new Invalid("source_registry_too_large");
        }
        try {
            StrictJson.Obj root = StrictJson.parseObject(data).exactly(TOP);
            wellFormed(root.node());
            if (!IngestionExportParser.SCHEMA_VERSION.equals(root.string("schemaVersion"))) {
                throw invalid();
            }
            nonEmpty(root.string("revision"));
            Map<String, SourceGrant> grants = new HashMap<>();
            List<StrictJson.Obj> sources = root.objects("sources");
            if (sources.size() > MAX_LIST) {
                throw invalid();
            }
            for (StrictJson.Obj source : sources) {
                String sourceId = nonEmpty(source.exactly(SOURCE).string("sourceId"));
                if (grants.put(sourceId, source(source, sourceId)) != null) {
                    throw invalid();
                }
            }
            return new SourceRegistry(Map.copyOf(grants));
        } catch (StrictJson.Malformed malformed) {
            throw invalid();
        }
    }

    private static SourceGrant source(StrictJson.Obj source, String sourceId) {
        if (!ADAPTERS.contains(source.string("adapter")) || !source.string("inputRoot").startsWith("/")) {
            throw invalid();
        }
        for (String host : bounded(source.strings("allowedHosts"), 1, MAX_LIST)) {
            // Python: `h != h.lower().rstrip(".")` or any of "/:@* " is refused; the empty host passes there and here.
            if (!host.equals(host.toLowerCase(Locale.ROOT)) || host.endsWith(".")
                    || host.chars().anyMatch(c -> "/:@* ".indexOf(c) >= 0)) {
                throw invalid();
            }
        }
        JsonNode scopes = source.array("scopes");
        if (scopes.size() < 1 || scopes.size() > MAX_LIST) {
            throw invalid();
        }
        Set<String> scopeIds = new HashSet<>();
        for (JsonNode node : scopes.values()) {
            StrictJson.Obj scope = StrictJson.Obj.of(node).exactly(SCOPE);
            if (!scopeIds.add(nonEmpty(scope.string("scopeId")))) {
                throw invalid();
            }
            String selection = nonEmpty(scope.string("selection"));
            if (Text.codePoints(selection) > MAX_SELECTION_CODE_POINTS) {
                throw invalid();
            }
            scope.stringOrNull("initialCursor");
            scope.stringOrNull("articleXPath");
            bounded(scope.strings("timestampLimitations"), 1, MAX_LIMITATIONS);
        }
        StrictJson.Obj grant = source.object("grant").exactly(GRANT);
        String grantId = nonEmpty(grant.string("grantId"));
        String revision = nonEmpty(grant.string("revision"));
        if (!sourceId.equals(nonEmpty(grant.string("sourceId")))) {
            throw invalid();
        }
        boolean enabled = grant.bool("enabled");
        String rights = grant.string("rights");
        List<String> operations = grant.strings("allowedOperations");
        grant.strings("recipients");
        grant.strings("purposes");
        List<String> evidence = grant.strings("evidence");
        String expiresAt = grant.stringOrNull("expiresAt");
        if (!RIGHTS.contains(rights) || !GRANTED.containsAll(operations)) {
            throw invalid();
        }
        return new SourceGrant(grantId, revision, enabled, rights, Set.copyOf(operations), List.copyOf(evidence),
                expiresAt == null ? null : expiry(expiresAt), Set.copyOf(source.strings("allowedHosts")));
    }

    private static Instant expiry(String value) {
        // ISO_OFFSET_DATE_TIME accepts lowercase 'z', but Python's registry parser rejects it.
        if (!EXPIRY.matcher(value).matches()) {
            throw new StrictJson.Malformed();
        }
        try {
            return IngestionExportParser.timestamp(value, DocumentImportFailure.EXPORT_INVALID);
        } catch (DocumentImportException refused) {
            throw new StrictJson.Malformed();
        }
    }

    /**
     * Every key and string must have a UTF-8 form: a JSON escape can produce an unpaired surrogate, which Python's reader
     * refuses.
     */
    private static void wellFormed(JsonNode node) {
        if (node.isString()) {
            wellFormed(node.stringValue());
        } else if (node.isObject()) {
            node.propertyNames().forEach(SourceRegistry::wellFormed);
            node.values().forEach(SourceRegistry::wellFormed);
        } else if (node.isArray()) {
            node.values().forEach(SourceRegistry::wellFormed);
        }
    }

    private static void wellFormed(String value) {
        if (Text.strictUtf8(value) == null) {
            throw new StrictJson.Malformed();
        }
    }

    private static List<String> bounded(List<String> values, int min, int max) {
        if (values.size() < min || values.size() > max) {
            throw new StrictJson.Malformed();
        }
        return values;
    }

    private static String nonEmpty(String value) {
        if (value.isEmpty()) {
            throw new StrictJson.Malformed();
        }
        return value;
    }

    private static Invalid invalid() {
        return new Invalid("source_registry_invalid");
    }

    /**
     * Whether the grant now in force for {@code sourceId} lets this app read, store and quote-display what it imported under
     * {@code (grantId, revision)}. Returns {@code null} to allow, otherwise a stable internal denial code for the log only
     * (never for a client). A routed leaf is read now, and {@code now} is the authority clock, never a requested
     * {@code asOf}. Expiry is inclusive of the instant it names.
     *
     * <p>Order of the codes: {@code source_unknown}, {@code grant_revision_or_source_changed},
     * {@code source_rights_unknown_or_denied} (disabled, rights other than {@code known}, or no non-blank evidence),
     * {@code source_grant_expired}, {@code source_operation_denied}.
     */
    public String denial(String sourceId, String grantId, String revision, Instant now) {
        if (routingPath != null) {
            unchanged();
            Path leaf = routes.get(new GrantKey(sourceId, grantId, revision));
            String result = leaf == null ? "source_unknown" : parse(readBounded(leaf)).denial(sourceId, grantId, revision, now);
            unchanged();
            return result;
        }
        SourceGrant grant = sourceId == null ? null : grants.get(sourceId);
        if (grant == null) {
            return "source_unknown";
        }
        if (!grant.grantId().equals(grantId) || !grant.revision().equals(revision)) {
            return "grant_revision_or_source_changed";
        }
        if (!grant.enabled() || !"known".equals(grant.rights()) || grant.evidence().stream().allMatch(SourceRegistry::blank)) {
            return "source_rights_unknown_or_denied";
        }
        if (grant.expiresAt() != null && !grant.expiresAt().isAfter(now)) {
            return "source_grant_expired";
        }
        if (!grant.operations().containsAll(OPERATIONS)) {
            return "source_operation_denied";
        }
        return null;
    }

    /** Explicit retained-file imports bind an article URL to the same current source's exact host allowlist. */
    public String denialForUrl(String sourceId, String grantId, String revision, String url, Instant now) {
        if (routingPath != null) {
            unchanged();
            Path leaf = routes.get(new GrantKey(sourceId, grantId, revision));
            String result = leaf == null ? "source_unknown" : parse(readBounded(leaf)).denialForUrl(sourceId, grantId, revision, url, now);
            unchanged();
            return result;
        }
        String denial = denial(sourceId, grantId, revision, now);
        if (denial != null) return denial;
        try {
            java.net.URI uri = java.net.URI.create(url);
            if (!Set.of("http", "https").contains(uri.getScheme()) || uri.getUserInfo() != null || uri.getHost() == null
                    || !grants.get(sourceId).allowedHosts().contains(uri.getHost().toLowerCase(Locale.ROOT)))
                return "source_url_outside_grant";
            return null;
        } catch (IllegalArgumentException invalid) {
            return "source_url_invalid";
        }
    }

    /** Pins local route ownership through a multi-step operation while leaves remain current authority. */
    public void checkRoutingUnchanged() {
        if (routingPath != null) unchanged();
    }

    private void unchanged() {
        if (!Arrays.equals(routingBytes, readBounded(routingPath))) throw invalid();
    }

    /**
     * Blank when every code point is white space, a space separator, a control or a format character (zero-width space,
     * byte-order mark). Stricter than Python's {@code strip()}: no invisible text is evidence.
     */
    private static boolean blank(String value) {
        return value.codePoints().allMatch(c -> Character.isWhitespace(c) || Character.isSpaceChar(c) || Character.isISOControl(c)
                || Character.getType(c) == Character.FORMAT);
    }

    /**
     * Static path/type/bound checks for an operator-controlled registry. On supporting providers directory opens are
     * descriptor-relative; on other providers the path check and open are separate. Neither branch makes leaf replacement
     * with a FIFO safe against a concurrent privileged local writer (Java has no nonblocking open for this channel).
     */
    private static byte[] readBounded(Path path) {
        try {
            Path absolute = path.toAbsolutePath().normalize();
            Path walk = absolute.getRoot();
            if (walk == null || absolute.getNameCount() == 0) {
                throw new Invalid("source_registry_unreadable");
            }
            BasicFileAttributes leaf = null;
            for (Path name : absolute) {
                walk = walk.resolve(name);
                leaf = Files.readAttributes(walk, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                if (leaf.isSymbolicLink()) {
                    throw new Invalid("source_registry_unreadable");
                }
            }
            if (!leaf.isRegularFile()) {
                throw new Invalid("source_registry_unreadable");
            }
            if (leaf.size() > MAX_BYTES) {
                throw new Invalid("source_registry_too_large");
            }
            PosixFileAttributeView permissions = Files.getFileAttributeView(absolute, PosixFileAttributeView.class,
                    LinkOption.NOFOLLOW_LINKS);
            if (permissions != null && writableByOthers(permissions.readAttributes().permissions())) {
                throw new Invalid("source_registry_unreadable");
            }
            try (DirectoryStream<Path> root = Files.newDirectoryStream(absolute.getRoot())) {
                if (root instanceof SecureDirectoryStream<Path> secure) {
                    return readAnchored(secure, absolute, 0);
                }
            }
            try (FileChannel channel = FileChannel.open(absolute, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                return readBytes(channel);
            }
        } catch (IOException | RuntimeException error) {
            if (error instanceof Invalid invalid) {
                throw invalid;
            }
            throw new Invalid("source_registry_unreadable");
        }
    }

    private static boolean writableByOthers(Set<PosixFilePermission> permissions) {
        return permissions.contains(PosixFilePermission.GROUP_WRITE) || permissions.contains(PosixFilePermission.OTHERS_WRITE);
    }

    private static byte[] readAnchored(SecureDirectoryStream<Path> parent, Path absolute, int index) throws IOException {
        Path name = absolute.getName(index);
        if (index == absolute.getNameCount() - 1) {
            BasicFileAttributes leaf = parent.getFileAttributeView(name, java.nio.file.attribute.BasicFileAttributeView.class,
                    LinkOption.NOFOLLOW_LINKS).readAttributes();
            if (!leaf.isRegularFile()) {
                throw new Invalid("source_registry_unreadable");
            }
            if (leaf.size() > MAX_BYTES) {
                throw new Invalid("source_registry_too_large");
            }
            PosixFileAttributeView permissions = parent.getFileAttributeView(name, PosixFileAttributeView.class,
                    LinkOption.NOFOLLOW_LINKS);
            if (permissions != null && writableByOthers(permissions.readAttributes().permissions())) {
                throw new Invalid("source_registry_unreadable");
            }
            try (SeekableByteChannel channel = parent.newByteChannel(name, READ_NOFOLLOW)) {
                return readBytes(channel);
            }
        }
        try (SecureDirectoryStream<Path> child = parent.newDirectoryStream(name, LinkOption.NOFOLLOW_LINKS)) {
            return readAnchored(child, absolute, index + 1);
        }
    }

    private static byte[] readBytes(ReadableByteChannel channel) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocate(MAX_BYTES + 1);
        while (buffer.hasRemaining() && channel.read(buffer) >= 0) {
            // read until the end of the file or one byte past the bound
        }
        if (buffer.position() > MAX_BYTES) {
            throw new Invalid("source_registry_too_large");
        }
        byte[] data = new byte[buffer.position()];
        buffer.flip().get(data);
        return data;
    }
}
