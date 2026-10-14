package com.zoop.common.json;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import tools.jackson.core.JacksonException;
import tools.jackson.core.StreamReadConstraints;
import tools.jackson.core.StreamReadFeature;
import tools.jackson.core.json.JsonFactory;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Strict JSON reading for the operator request, the S2-1 export and AI results: UTF-8 only, no duplicate keys, no trailing
 * tokens, bounded nesting, exact key sets. The same mapper configuration as the AI wire reader, replicated here because that
 * reader is package-private to the AI transport. {@link Malformed} carries nothing: callers pick the failure code.
 */
public final class StrictJson {
    private static final JsonMapper MAPPER = JsonMapper.builder(JsonFactory.builder()
                    .streamReadConstraints(StreamReadConstraints.builder().maxNestingDepth(64).build()).build())
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
            .build();

    public static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");

    private StrictJson() {
    }

    public static final class Malformed extends RuntimeException {
        public Malformed() {
            super("malformed", null, false, false);
        }
    }

    public static ObjectNode newObject() {
        return MAPPER.createObjectNode();
    }

    public static ArrayNode newArray() {
        return MAPPER.createArrayNode();
    }

    public static byte[] write(JsonNode node) {
        try {
            return MAPPER.writeValueAsBytes(node);
        } catch (JacksonException error) {
            throw new Malformed();
        }
    }

    /** Strict UTF-8 decoding of a whole document, then a JSON object (any other top-level value is malformed). */
    public static Obj parseObject(byte[] bytes) {
        String text;
        try {
            text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException error) {
            throw new Malformed();
        }
        try {
            return Obj.of(MAPPER.readTree(text));
        } catch (JacksonException error) {
            throw new Malformed();
        }
    }

    /** The same as {@link #parseObject(byte[])} for a string that is already decoded; it must have a UTF-8 form. */
    public static Obj parseObject(String text) {
        byte[] bytes = Text.strictUtf8(text);
        if (bytes == null) {
            throw new Malformed();
        }
        return parseObject(bytes);
    }

    /** A JSON object with explicit, typed access; nothing is coerced. */
    public record Obj(JsonNode node) {
        public static Obj of(JsonNode node) {
            if (node == null || !node.isObject()) {
                throw new Malformed();
            }
            return new Obj(node);
        }

        /** The object has exactly these keys: none missing and none unknown. */
        public Obj exactly(Set<String> keys) {
            return keys(keys, Set.of());
        }

        /** Every {@code required} key is present and no key outside {@code required} and {@code optional} is. */
        public Obj keys(Set<String> required, Set<String> optional) {
            Set<String> present = Set.copyOf(node.propertyNames());
            if (!present.containsAll(required) || !required.containsAll(present.stream()
                    .filter(key -> !optional.contains(key)).toList())) {
                throw new Malformed();
            }
            return this;
        }

        /** Every {@code required} key is present; further keys are ignored (never copied anywhere by the caller). */
        public Obj requiring(Set<String> required) {
            if (!Set.copyOf(node.propertyNames()).containsAll(required)) {
                throw new Malformed();
            }
            return this;
        }

        public boolean has(String name) {
            return node.has(name);
        }

        public boolean isNull(String name) {
            return required(name).isNull();
        }

        public String string(String name) {
            JsonNode value = required(name);
            if (!value.isString()) {
                throw new Malformed();
            }
            return value.stringValue();
        }

        /** A string or an explicit JSON null (absence is malformed). */
        public String stringOrNull(String name) {
            return isNull(name) ? null : string(name);
        }

        /** A JSON integer in {@code [0, Integer.MAX_VALUE]}. */
        public int count(String name) {
            JsonNode value = required(name);
            if (!value.isIntegralNumber() || !value.canConvertToInt() || value.intValue() < 0) {
                throw new Malformed();
            }
            return value.intValue();
        }

        public boolean bool(String name) {
            JsonNode value = required(name);
            if (!value.isBoolean()) {
                throw new Malformed();
            }
            return value.booleanValue();
        }

        public Obj object(String name) {
            return of(required(name));
        }

        public JsonNode array(String name) {
            JsonNode value = required(name);
            if (!value.isArray()) {
                throw new Malformed();
            }
            return value;
        }

        /** An array of strings. */
        public List<String> strings(String name) {
            List<String> items = new ArrayList<>();
            for (JsonNode item : array(name).values()) {
                if (!item.isString()) {
                    throw new Malformed();
                }
                items.add(item.stringValue());
            }
            return items;
        }

        /** An array of objects. */
        public List<Obj> objects(String name) {
            List<Obj> items = new ArrayList<>();
            for (JsonNode item : array(name).values()) {
                items.add(of(item));
            }
            return items;
        }

        /** Any value of the object, present (possibly null). */
        public JsonNode raw(String name) {
            return required(name);
        }

        private JsonNode required(String name) {
            JsonNode value = node.get(name);
            if (value == null) {
                throw new Malformed();
            }
            return value;
        }
    }
}
