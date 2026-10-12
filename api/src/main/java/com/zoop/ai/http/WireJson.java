package com.zoop.ai.http;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.function.Function;
import java.util.regex.Pattern;

import tools.jackson.core.JacksonException;
import tools.jackson.core.StreamReadConstraints;
import tools.jackson.core.StreamReadFeature;
import tools.jackson.core.json.JsonFactory;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Strict JSON reading for AI wire documents: UTF-8 only, no duplicate keys, no trailing tokens, bounded nesting, exact
 * decimals. Anything unexpected is {@link Malformed}, which carries a field path and never a value.
 */
final class WireJson {
    private static final JsonMapper MAPPER = JsonMapper.builder(JsonFactory.builder()
                    .streamReadConstraints(StreamReadConstraints.builder().maxNestingDepth(64).build()).build())
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
            .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
            .build();

    private WireJson() {
    }

    static final class Malformed extends RuntimeException {
        Malformed(String path) {
            super("malformed " + path, null, false, false);
        }
    }

    static String utf8(byte[] bytes) {
        try {
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException error) {
            throw new Malformed("encoding");
        }
    }

    static JsonNode parse(String text, String path) {
        try {
            JsonNode node = MAPPER.readTree(text);
            if (node == null || !node.isObject()) {
                throw new Malformed(path);
            }
            return node;
        } catch (JacksonException error) {
            throw new Malformed(path);
        }
    }

    static String compact(JsonNode node) {
        try {
            return MAPPER.writeValueAsString(node);
        } catch (JacksonException error) {
            throw new Malformed("payload");
        }
    }

    /** A typed view over one JSON object whose keys are all required. */
    record Obj(JsonNode node, String path) {
        static final Pattern SAFE = Pattern.compile("[A-Za-z0-9_.:-]{1,80}");
        static final Pattern PRINTABLE = Pattern.compile("[\\x20-\\x7E]{1,120}");
        static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");

        static Obj of(JsonNode node, String path) {
            if (node == null || !node.isObject()) {
                throw new Malformed(path);
            }
            return new Obj(node, path);
        }

        private JsonNode required(String name) {
            JsonNode value = node.get(name);
            if (value == null) {
                throw new Malformed(path + "." + name);
            }
            return value;
        }

        private Malformed bad(String name) {
            return new Malformed(path + "." + name);
        }

        String string(String name, Pattern pattern) {
            JsonNode value = required(name);
            if (!value.isString() || !pattern.matcher(value.stringValue()).matches()) {
                throw bad(name);
            }
            return value.stringValue();
        }

        Optional<String> optString(String name, Pattern pattern) {
            JsonNode value = required(name);
            if (value.isNull()) {
                return Optional.empty();
            }
            if (!value.isString() || !pattern.matcher(value.stringValue()).matches()) {
                throw bad(name);
            }
            return Optional.of(value.stringValue());
        }

        long count(String name) {
            JsonNode value = required(name);
            if (!value.isIntegralNumber() || !value.canConvertToLong() || value.longValue() < 0) {
                throw bad(name);
            }
            return value.longValue();
        }

        Long optCount(String name) {
            return required(name).isNull() ? null : count(name);
        }

        Double optNumber(String name) {
            JsonNode value = required(name);
            if (value.isNull()) {
                return null;
            }
            if (!value.isNumber() || !Double.isFinite(value.doubleValue()) || value.doubleValue() < 0) {
                throw bad(name);
            }
            return value.doubleValue();
        }

        boolean bool(String name) {
            JsonNode value = required(name);
            if (!value.isBoolean()) {
                throw bad(name);
            }
            return value.booleanValue();
        }

        Obj object(String name) {
            return of(required(name), path + "." + name);
        }

        Optional<Obj> optObject(String name) {
            JsonNode value = required(name);
            return value.isNull() ? Optional.empty() : Optional.of(of(value, path + "." + name));
        }

        JsonNode raw(String name) {
            return required(name);
        }

        List<JsonNode> array(String name, int max) {
            JsonNode value = required(name);
            if (!value.isArray() || value.size() > max) {
                throw bad(name);
            }
            List<JsonNode> items = new ArrayList<>(value.size());
            value.values().forEach(items::add);
            return items;
        }

        List<String> strings(String name, int max, Pattern pattern) {
            List<String> items = new ArrayList<>();
            for (JsonNode item : array(name, max)) {
                if (!item.isString() || !pattern.matcher(item.stringValue()).matches()) {
                    throw bad(name);
                }
                items.add(item.stringValue());
            }
            return items;
        }

        <E> E choice(String name, Function<String, Optional<E>> parser) {
            return parser.apply(string(name, PRINTABLE)).orElseThrow(() -> bad(name));
        }

        <E> Optional<E> optChoice(String name, Function<String, Optional<E>> parser) {
            return optString(name, PRINTABLE).map(value -> parser.apply(value).orElseThrow(() -> bad(name)));
        }
    }
}
