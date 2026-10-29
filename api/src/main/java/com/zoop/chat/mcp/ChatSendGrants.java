package com.zoop.chat.mcp;

import com.zoop.common.json.StrictJson;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.function.Predicate;

/**
 * The model-send gate of MCP results (api/docs/chat-mcp.md 5): may text of a source reach the agent model. A hosted MCP
 * result goes from this endpoint to the model provider directly, past the AI service's own grant check, so the endpoint reads
 * the same operator-owned chat grant registry ({@code zoop-ai-chat-1}, the file the AI runtime takes as {@code --grants})
 * and applies the AI runtime's rule for the {@code chat-agent} stage: an enabled grant of the source with known rights,
 * {@code model-send}, {@code chat-agent} among its purposes (that stage stores its responses for continuations,
 * {@code store=true}), the agent's exact recipient ({@code <provider>:<revision>} as the AI runtime names it) and not
 * expired.
 *
 * <p>The file is read again for every check, so a withdrawn grant applies to the next result. A registry that cannot be read
 * or does not have the strict shape allows nothing ({@link Unavailable}); it is never treated as an empty allowance.
 */
public final class ChatSendGrants {
    static final String SCHEMA = "zoop-ai-chat-1";
    static final String PURPOSE = "chat-agent";
    static final int MAX_REGISTRY_BYTES = 1_000_000;
    private static final Set<String> FIELDS = Set.of("grantId", "revision", "sourceId", "enabled", "rights",
            "allowedOperations", "recipients", "purposes", "evidence", "expiresAt");
    private static final Set<String> RIGHTS = Set.of("known", "unknown", "denied");
    private static final Set<String> OPERATIONS = Set.of("read", "model-send", "quote-display");
    private static final Set<String> STAGES = Set.of("chat-router", "chat-answer", "chat-verification", "chat-agent");

    /** The registry could not be read or is malformed; nothing may be sent. Carries no path or content. */
    public static final class Unavailable extends RuntimeException {
        Unavailable() {
            super("chat grant registry unavailable", null, false, false);
        }
    }

    private record Grant(String sourceId, boolean enabled, String rights, List<String> operations, List<String> recipients,
            List<String> purposes, OffsetDateTime expiresAt) {
    }

    private final Path registry;
    private final String recipient;
    private final Clock clock;

    /**
     * {@code registry} is an absolute, normalized path and {@code recipient} the agent stage's recipient; either missing
     * fails with the settings' names ({@code ZOOP_CHAT_MCP_SEND_GRANTS}, {@code ZOOP_CHAT_MCP_SEND_RECIPIENT}).
     */
    public ChatSendGrants(String registry, String recipient, Clock clock) {
        Path path;
        try {
            path = registry == null || registry.isBlank() ? null : Path.of(registry.strip());
        } catch (RuntimeException invalid) {
            path = null;
        }
        if (path == null || !path.isAbsolute() || !path.equals(path.normalize())
                || recipient == null || recipient.isBlank() || !recipient.equals(recipient.strip())) {
            throw new IllegalArgumentException("Invalid chat MCP send grant configuration "
                    + "(ZOOP_CHAT_MCP_SEND_GRANTS: an absolute normalized path, ZOOP_CHAT_MCP_SEND_RECIPIENT: the agent recipient)");
        }
        this.registry = path;
        this.recipient = recipient;
        this.clock = clock;
    }

    /**
     * The agent recipient the grants are checked for. Every agent step names it, and the AI runtime sends a step only when it
     * is the stage's own recipient, so results are never checked for one recipient and received by another.
     */
    public String recipient() {
        return recipient;
    }

    /** The sources whose text may be sent to the agent now. Throws {@link Unavailable} when the registry cannot be used. */
    public Predicate<String> sendable() {
        List<Grant> grants = load();
        OffsetDateTime now = OffsetDateTime.now(clock);
        return source -> source != null && grants.stream().anyMatch(g -> g.sourceId().equals(source) && g.enabled()
                && "known".equals(g.rights()) && g.operations().contains("model-send") && g.purposes().contains(PURPOSE)
                && g.recipients().contains(recipient) && (g.expiresAt() == null || g.expiresAt().isAfter(now)));
    }

    private List<Grant> load() {
        byte[] data;
        try (InputStream in = Files.newInputStream(registry)) {
            data = in.readNBytes(MAX_REGISTRY_BYTES + 1);
        } catch (IOException | RuntimeException unreadable) {
            throw new Unavailable();
        }
        if (data.length > MAX_REGISTRY_BYTES) throw new Unavailable();
        try {
            return parse(data);
        } catch (StrictJson.Malformed | DateTimeParseException malformed) {
            throw new Unavailable();
        }
    }

    /** The registry's grants, with the strict shape the AI runtime's own model of it accepts. */
    static List<Grant> parse(byte[] data) {
        var root = StrictJson.parseObject(data).exactly(Set.of("schemaVersion", "grants"));
        if (!SCHEMA.equals(root.string("schemaVersion"))) throw new StrictJson.Malformed();
        List<Grant> grants = new ArrayList<>();
        for (var g : root.objects("grants")) {
            g.exactly(FIELDS);
            for (String id : List.of("grantId", "revision", "sourceId")) {
                if (g.string(id).isEmpty()) throw new StrictJson.Malformed();
            }
            List<String> operations = g.strings("allowedOperations");
            List<String> purposes = g.strings("purposes");
            g.strings("evidence");
            String rights = g.string("rights");
            if (!RIGHTS.contains(rights) || !OPERATIONS.containsAll(operations) || !STAGES.containsAll(purposes)) {
                throw new StrictJson.Malformed();
            }
            String expiry = g.stringOrNull("expiresAt");
            // A grant expiry carries its offset, as the AI runtime requires.
            OffsetDateTime expiresAt = expiry == null ? null : OffsetDateTime.parse(expiry);
            grants.add(new Grant(g.string("sourceId"), g.bool("enabled"), rights, operations, g.strings("recipients"),
                    purposes, expiresAt));
        }
        return grants;
    }
}
