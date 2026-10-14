package com.zoop.common.json;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * The canonical JSON of the AI runtime is Python's {@code json.dumps(value, ensure_ascii=False, sort_keys=True,
 * separators=(",", ":"))}. The expected strings and digests below were produced by Python itself (3.12), independently of
 * this code: that is what lets the app recompute the worker's artifact ids and result versions instead of trusting them.
 */
class CanonicalTest {

    @Test
    void matchesPythonOnNestedMixedContent() {
        ObjectNode node = StrictJson.newObject();
        node.put("b", 1);
        node.putArray("a").add(true).add(false).addNull();
        ObjectNode inner = node.putObject("c");
        inner.put("z", "한");
        inner.put("y", "\uD83D\uDE00");
        inner.put("x", "");
        node.put("A", "upper");
        node.put("_", 0);

        assertEquals("{\"A\":\"upper\",\"_\":0,\"a\":[true,false,null],\"b\":1,\"c\":{\"x\":\"\",\"y\":\"\uD83D\uDE00\",\"z\":\"한\"}}",
                Canonical.write(node));
        assertEquals("ca04781e350f1d3b5ebf994b0349c634e1b287e3c31892e55e7b6e93229b71ba", Canonical.digest(node));
    }

    @Test
    void escapesExactlyWhatPythonEscapes() {
        ObjectNode node = StrictJson.newObject();
        node.put("s", "a\"b\\c\n\r\t\b\f\u0001\u001f\u007f\u2028\u2029/\u00e9\u00a0");

        // Quote, backslash, the five short escapes and other C0 controls (lowercase hex) only; DEL, U+2028/2029, "/" and
        // non-ASCII text stay verbatim.
        assertEquals("{\"s\":\"a\\\"b\\\\c\\n\\r\\t\\b\\f\\u0001\\u001f\u007f\u2028\u2029/\u00e9\u00a0\"}", Canonical.write(node));
        assertEquals("d5d209ea09627c2ed103f6e577baa83d50e9e75fd3f9f26b5c4983c8be95bda9", Canonical.digest(node));
    }

    @Test
    void writesIntegersOfAnySizeAndEmptyContainers() {
        ObjectNode node = (ObjectNode) StrictJson.parseObject(
                "{\"neg\":-42,\"big\":12345678901234567890,\"zero\":0,\"arr\":[1,[2,[3,[]]],{}]}").node();

        assertEquals("{\"arr\":[1,[2,[3,[]]],{}],\"big\":12345678901234567890,\"neg\":-42,\"zero\":0}", Canonical.write(node));
        assertEquals("7b0a2d14fc57c2e5d200a63b9d795ec3cadaa8e5f626f71e08243aee54090b37", Canonical.digest(node));
        assertEquals("{}", Canonical.write(StrictJson.newObject()));
        assertEquals("44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a", Canonical.digest(StrictJson.newObject()));
    }

    @Test
    void refusesWhatPythonAndJavaWouldWriteDifferently() {
        ObjectNode floating = StrictJson.newObject();
        floating.put("a", 1.5);
        assertThrows(StrictJson.Malformed.class, () -> Canonical.write(floating));

        ObjectNode koreanKey = StrictJson.newObject();
        koreanKey.put("한", "x");
        assertThrows(StrictJson.Malformed.class, () -> Canonical.write(koreanKey));

        ObjectNode unpaired = StrictJson.newObject();
        unpaired.put("a", "\uD800");
        assertThrows(StrictJson.Malformed.class, () -> Canonical.write(unpaired));
        assertThrows(StrictJson.Malformed.class, () -> Canonical.writeApp(unpaired));
    }

    @Test
    void theAppFormAlsoWritesFiniteFloatsDeterministically() {
        ObjectNode node = StrictJson.newObject();
        node.put("b", 1.5);
        node.put("a", 12.0);

        assertEquals("{\"a\":12.0,\"b\":1.5}", Canonical.writeApp(node));
        assertEquals(Canonical.writeApp(node), Canonical.writeApp(node.deepCopy()));
        ObjectNode infinite = StrictJson.newObject();
        infinite.put("a", Double.POSITIVE_INFINITY);
        assertThrows(StrictJson.Malformed.class, () -> Canonical.writeApp(infinite));
    }

    @Test
    void codePointSlicesNeverUseUtf16Units() {
        String text = "\uD83D\uDE00\uD83C\uDDF0\uD83C\uDDF7 한글";

        assertEquals("\uD83D\uDE00", Text.codePointSlice(text, 0, 1));
        assertEquals("\uD83C\uDDF0\uD83C\uDDF7", Text.codePointSlice(text, 1, 3));
        assertEquals("한글", Text.codePointSlice(text, 4, 6));
        assertEquals(text, Text.codePointSlice(text, 0, 6));
        assertNull(Text.codePointSlice(text, 0, 7), "the end is exclusive and must fit");
        assertNull(Text.codePointSlice(text, 3, 3));
        assertNull(Text.codePointSlice(text, -1, 2));
        assertNull(Text.codePointSlice(text, 5, 4));
    }
}
