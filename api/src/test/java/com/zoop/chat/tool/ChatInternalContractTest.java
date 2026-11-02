package com.zoop.chat.tool;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/** Keeps the language-neutral Stage 0 chatbot schemas pinned to the Java request and registry constants. */
class ChatInternalContractTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final Path CONTRACTS = Path.of("..", "docs", "api");

    @Test
    void requestSchemaTracksCapabilitiesAndRuntimeBounds() throws IOException {
        JsonNode schema = read("chat-tool-request.schema.json");
        Set<String> schemaCapabilities = new LinkedHashSet<>();
        schema.at("/$defs/capabilityId/enum").forEach(value -> schemaCapabilities.add(value.asString()));
        Set<String> runtimeCapabilities = new LinkedHashSet<>();
        Arrays.stream(ChatCapability.values()).map(ChatCapability::id).forEach(runtimeCapabilities::add);

        assertEquals(runtimeCapabilities, schemaCapabilities);
        assertEquals(ChatToolRequest.MAX_TARGETS, schema.at("/properties/targets/maxItems").asInt());
        assertEquals(ChatToolRequest.MAX_LIMIT, schema.at("/properties/limit/maximum").asInt());
        assertEquals(ChatToolRegistry.SCHEMA_VERSION,
                read("chat-tool-result.schema.json").at("/properties/schemaVersion/const").asString());
    }

    @Test
    void portableRequestFixturesRoundTripThroughTheJavaRecord() throws IOException {
        JsonNode fixture = read("fixtures/chat-internal-contracts.json");
        for (JsonNode value : fixture.path("requests")) {
            ChatToolRequest request = new ChatToolRequest(value.path("capabilityId").asString(), strings(value, "targets"),
                    value.path("limit").asInt(), value.has("evidenceScope") ? strings(value, "evidenceScope") : null,
                    value.has("since") ? Instant.parse(value.path("since").asString()) : null,
                    value.has("searchText") ? value.path("searchText").asString() : null);
            ObjectNode encoded = JSON.valueToTree(request);
            encoded.properties().removeIf(entry -> entry.getValue().isNull());
            assertEquals(value, encoded);
        }
        assertTrue(fixture.path("results").size() >= 2, "fixtures cover both successful and failed results");
        assertTrue(fixture.path("routeSummaries").size() >= 2, "fixtures cover answered and stopped routes");
    }

    private static List<String> strings(JsonNode node, String field) {
        return JSON.convertValue(node.path(field), JSON.getTypeFactory().constructCollectionType(List.class, String.class));
    }

    private static JsonNode read(String relative) throws IOException {
        return JSON.readTree(Files.readString(CONTRACTS.resolve(relative)));
    }
}
