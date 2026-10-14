package com.zoop.document.analysis;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;

/**
 * Current-authority reader for the operator-owned flat S1 grant registry, ported rule for rule from
 * {@code ai/service/.../grants.py} ({@code parse} and {@code evaluate}, no Python import). The file is read fresh for every
 * decision; nothing is cached and nothing is written back.
 *
 * <p>It is at parity with the Python reader or stricter, never looser: JSON with duplicate keys is refused (Python keeps the
 * last), and an {@code expiresAt} that {@link OffsetDateTime#parse} cannot read denies that grant (Python's
 * {@code fromisoformat} reads more forms), so a doubtful date fails closed. The failure code is one of
 * {@code grant_registry_too_large}, {@code grant_registry_unreadable}, {@code grant_registry_schema_invalid} and
 * {@code grant_revision_conflict}; none carries registry content or a path.
 */
public final class GrantRegistry {
    public static final String SCHEMA = "zoop-ai-s1-1";
    public static final int MAX_BYTES = 1_000_000;
    public static final Set<String> OPERATIONS = Set.of("read", "store", "model-send", "quote-display");
    public static final String REPLAY_RECIPIENT = "authored-replay";

    private static final Set<String> KINDS = Set.of("document-summary", "document-sentiment", "semantic-verification",
            "briefing-outlook");
    private static final Set<String> RIGHTS = Set.of("known", "unknown", "denied");
    private static final Set<String> FIELDS = Set.of("grantId", "revision", "sourceId", "enabled", "rights", "allowedOperations",
            "recipients", "purposes", "evidence", "expiresAt");
    private static final Set<String> NAVER_SEARCH = Set.of("naver-search", "naver-developers-search");

    private final Map<String, FlatGrant> current;

    private GrantRegistry(Map<String, FlatGrant> current) {
        this.current = current;
    }

    /** The grant now in force for {@code grantId}: in a file listing several revisions, the last one listed. */
    public Optional<FlatGrant> current(String grantId) {
        return Optional.ofNullable(current.get(grantId));
    }

    public static GrantRegistry read(Path path) {
        byte[] data;
        try (InputStream stream = Files.newInputStream(path)) {
            data = stream.readNBytes(MAX_BYTES + 1);
        } catch (IOException | RuntimeException error) {
            throw unavailable("grant_registry_unreadable");
        }
        return parse(data);
    }

    public static GrantRegistry parse(byte[] data) {
        if (data.length > MAX_BYTES) {
            throw unavailable("grant_registry_too_large");
        }
        StrictJson.Obj root;
        try {
            root = StrictJson.parseObject(data);
        } catch (StrictJson.Malformed malformed) {
            throw unavailable("grant_registry_unreadable");
        }
        Map<String, FlatGrant> current = new HashMap<>();
        Map<String, FlatGrant> history = new HashMap<>();
        try {
            root.requiring(Set.of("schemaVersion", "grants"));
            if (!SCHEMA.equals(root.string("schemaVersion"))) {
                throw unavailable("grant_registry_schema_invalid");
            }
            for (JsonNode node : root.array("grants").values()) {
                FlatGrant grant = grant(StrictJson.Obj.of(node));
                String key = grant.grantId() + '\u0000' + grant.revision();
                // The runtime refuses a changed payload under an already registered revision; the file must not contain one.
                FlatGrant earlier = history.get(key);
                if (earlier != null && !earlier.equals(grant)) {
                    throw unavailable("grant_revision_conflict");
                }
                history.put(key, grant);
                current.put(grant.grantId(), grant);
            }
        } catch (StrictJson.Malformed malformed) {
            throw unavailable("grant_registry_schema_invalid");
        }
        return new GrantRegistry(Map.copyOf(current));
    }

    private static FlatGrant grant(StrictJson.Obj obj) {
        obj.exactly(FIELDS);
        String grantId = nonEmpty(obj.string("grantId"));
        String revision = nonEmpty(obj.string("revision"));
        String sourceId = nonEmpty(obj.string("sourceId"));
        String rights = obj.string("rights");
        List<String> operations = obj.strings("allowedOperations");
        List<String> purposes = obj.strings("purposes");
        if (!RIGHTS.contains(rights) || !OPERATIONS.containsAll(operations) || !KINDS.containsAll(purposes)) {
            throw new StrictJson.Malformed();
        }
        return new FlatGrant(grantId, revision, sourceId, obj.bool("enabled"), rights, operations, obj.strings("recipients"),
                purposes, obj.strings("evidence"), obj.stringOrNull("expiresAt"));
    }

    private static String nonEmpty(String value) {
        if (value.isEmpty()) {
            throw new StrictJson.Malformed();
        }
        return value;
    }

    /**
     * Returns a stable denial code, or {@code null} when current authority covers the use. Same order as the service and the
     * runtime. An empty recipient list is never an authorization when {@code requireRecipients} is set; a prepare for a live
     * job cannot name its recipient before a call exists and passes {@code false} (the worker, the service and the settlement
     * check the recipient later).
     */
    public static String evaluate(FlatGrant grant, String sourceId, String revision, List<String> purposes,
            List<String> recipients, boolean requireRecipients, Instant now) {
        if (grant == null || !"known".equals(grant.rights()) || !grant.enabled() || grant.evidence().isEmpty()) {
            return "source_rights_unknown_or_denied";
        }
        if (!grant.revision().equals(revision) || !grant.sourceId().equals(sourceId)) {
            return "grant_revision_or_source_changed";
        }
        if (NAVER_SEARCH.contains(grant.sourceId().toLowerCase(Locale.ROOT).replace('_', '-'))) {
            return "naver_search_ai_prohibited";
        }
        if (grant.expiresAt() != null) {
            Instant expiry;
            try {
                expiry = OffsetDateTime.parse(grant.expiresAt()).toInstant();
            } catch (DateTimeException error) {
                return "source_grant_expiry_invalid";
            }
            if (!expiry.isAfter(now)) {
                return "source_grant_expired";
            }
        }
        if (!grant.allowedOperations().containsAll(OPERATIONS)) {
            return "source_operation_denied";
        }
        boolean recipientsGranted = !requireRecipients || (!recipients.isEmpty() && grant.recipients().containsAll(recipients));
        if (!recipientsGranted || !grant.purposes().containsAll(purposes)) {
            return "source_purpose_or_recipient_denied";
        }
        return null;
    }

    /** The purposes a document analysis needs: its own kind and the independent semantic verification. */
    public static List<String> purposesOf(String kindWire) {
        List<String> purposes = new ArrayList<>();
        purposes.add(kindWire);
        purposes.add("semantic-verification");
        return purposes;
    }

    private static AnalysisException unavailable(String detail) {
        return AnalysisException.of(AnalysisFailure.GRANT_REGISTRY_UNAVAILABLE, "registry", detail);
    }
}
