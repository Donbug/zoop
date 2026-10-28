package com.zoop.chat.mcp;

import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * Issues and verifies the job-scoped bearer tokens of the chat MCP endpoint ({@link ChatMcpGrant}). A token is
 * {@code zmcp1.<keyId>.<payload>.<mac>}: the canonical JSON grant and an HMAC-SHA256 over the prefix, key id and payload under
 * its own purpose, both base64url. Keys come from {@code ZOOP_CHAT_MCP_KEYS} ({@code id=base64url,...}, each at least 32
 * bytes), separate from the CSRF keys because these tokens leave the service (the model provider sends them back); the
 * active one signs and every listed one verifies, so keys can rotate. Key material and tokens are never logged.
 */
public final class ChatMcpGrants {
    static final String PREFIX = "zmcp1";
    private static final String PURPOSE = "zoop-chat-mcp-grant-v1";
    private static final String KEY_ID = "[A-Za-z0-9_-]{1,64}";
    private static final int MAX_TOKEN_LENGTH = 4096;
    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Set<String> FIELDS = Set.of("job", "attempt", "tools", "graphVersion", "asOf", "exp");

    private final String activeKeyId;
    private final Map<String, byte[]> keys;
    private final Clock clock;

    public ChatMcpGrants(String activeKeyId, String encodedKeys, Clock clock) {
        if (activeKeyId == null || !activeKeyId.matches(KEY_ID)) throw invalidConfiguration();
        Map<String, byte[]> parsed = new HashMap<>();
        if (encodedKeys != null && !encodedKeys.isBlank()) {
            for (String entry : encodedKeys.split(",", -1)) {
                String[] parts = entry.split("=", 2);
                if (parts.length != 2 || !parts[0].matches(KEY_ID)) throw invalidConfiguration();
                byte[] key;
                try {
                    key = Base64.getUrlDecoder().decode(parts[1]);
                } catch (IllegalArgumentException malformed) {
                    throw invalidConfiguration();
                }
                if (key.length < 32 || parsed.putIfAbsent(parts[0], key) != null) throw invalidConfiguration();
            }
        }
        if (!parsed.containsKey(activeKeyId)) throw invalidConfiguration();
        this.activeKeyId = activeKeyId;
        this.keys = Collections.unmodifiableMap(parsed);
        this.clock = clock;
    }

    /**
     * A token for {@code run}'s attempt that allows {@code tools} and expires with the run's deadline. The member scope read
     * is never grantable: Q07's scope is fixed by the server before a model sees anything.
     */
    public String issue(ChatRun run, Collection<ChatCapability> tools) {
        ChatMcpGrant grant = new ChatMcpGrant(run.jobId(), run.attemptNo(), List.copyOf(tools), run.graphVersionId(),
                run.context().asOf(), run.deadline());
        var payload = StrictJson.newObject();
        payload.put("job", grant.jobId());
        payload.put("attempt", grant.attemptNo());
        var ids = payload.putArray("tools");
        grant.tools().forEach(tool -> ids.add(tool.id()));
        payload.put("graphVersion", grant.graphVersionId());
        payload.put("asOf", grant.asOf() == null ? null : grant.asOf().toString());
        payload.put("exp", grant.expiresAt().toString());
        String signed = PREFIX + "." + activeKeyId + "." + ENCODER.encodeToString(Canonical.bytes(payload));
        return signed + "." + ENCODER.encodeToString(mac(keys.get(activeKeyId), signed));
    }

    /** The grant of a well-formed, correctly signed and unexpired token; empty for anything else. */
    public Optional<ChatMcpGrant> verify(String token) {
        if (token == null || token.length() > MAX_TOKEN_LENGTH) return Optional.empty();
        String[] parts = token.split("\\.", -1);
        if (parts.length != 4 || !PREFIX.equals(parts[0])) return Optional.empty();
        byte[] key = keys.get(parts[1]);
        if (key == null) return Optional.empty();
        byte[] given;
        byte[] payload;
        try {
            given = Base64.getUrlDecoder().decode(parts[3]);
            payload = Base64.getUrlDecoder().decode(parts[2]);
        } catch (IllegalArgumentException malformed) {
            return Optional.empty();
        }
        if (!MessageDigest.isEqual(given, mac(key, parts[0] + "." + parts[1] + "." + parts[2]))) return Optional.empty();
        ChatMcpGrant grant;
        try {
            var fields = StrictJson.parseObject(payload).exactly(FIELDS);
            List<ChatCapability> tools = new ArrayList<>();
            for (String id : fields.strings("tools")) {
                tools.add(ChatCapability.of(id).orElseThrow(() -> new IllegalArgumentException("unknown tool")));
            }
            String asOf = fields.stringOrNull("asOf");
            grant = new ChatMcpGrant(fields.string("job"), fields.count("attempt"), tools,
                    fields.stringOrNull("graphVersion"), asOf == null ? null : Instant.parse(asOf),
                    Instant.parse(fields.string("exp")));
        } catch (StrictJson.Malformed | IllegalArgumentException | DateTimeParseException malformed) {
            // Signed by us but unreadable: a key reused elsewhere or a format from another version. Never a grant.
            return Optional.empty();
        }
        return clock.instant().isBefore(grant.expiresAt()) ? Optional.of(grant) : Optional.empty();
    }

    private static byte[] mac(byte[] key, String signed) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            mac.update(PURPOSE.getBytes(StandardCharsets.US_ASCII));
            mac.update((byte) 0);
            return mac.doFinal(signed.getBytes(StandardCharsets.US_ASCII));
        } catch (NoSuchAlgorithmException | InvalidKeyException unavailable) {
            throw new IllegalStateException("chat MCP grant signing unavailable", unavailable);
        }
    }

    private static IllegalArgumentException invalidConfiguration() {
        return new IllegalArgumentException("Invalid chat MCP key configuration (ZOOP_CHAT_MCP_ACTIVE_KEY_ID, ZOOP_CHAT_MCP_KEYS)");
    }
}
