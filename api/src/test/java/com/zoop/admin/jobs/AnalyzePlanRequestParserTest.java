package com.zoop.admin.jobs;

import static org.junit.jupiter.api.Assertions.*;

import com.zoop.common.exception.CustomException;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.Test;

class AnalyzePlanRequestParserTest {
    private static final String PLAN = "{\"planId\":\"s2plan-" + "a".repeat(64) + "\",\"planDigest\":\"" + "b".repeat(64) + "\"}";
    private static final String VALID = "{\"kind\":\"analyze_plan\",\"reason\":\" 운영 확인 \",\"plan\":" + PLAN + "}";

    @Test
    void acceptsOnlyTheClosedTypedPlanCommandAndNormalizesTheReason() throws Exception {
        var parsed = parse(VALID);
        assertEquals("운영 확인", parsed.reason());
        assertEquals("s2plan-" + "a".repeat(64), parsed.plan().planId());
        assertEquals("b".repeat(64), parsed.plan().planDigest());
    }

    @Test
    void refusesDuplicatesTrailingJsonCoercionsUnknownAndMixedShapes() {
        for (String body : List.of(VALID + "{}", VALID.replace("\"kind\":", "\"kind\":\"analyze_plan\",\"kind\":"),
                VALID.replace("\"plan\":", "\"sourceId\":\"source\",\"plan\":"),
                VALID.replace("\"plan\":", "\"candidateIds\":[],\"plan\":"),
                VALID.replace("\"planDigest\":", "\"unknown\":null,\"planDigest\":"),
                VALID.replace("\" 운영 확인 \"", "true"), VALID.replace("\"plan\":" + PLAN, "\"plan\":null"),
                VALID.replace("s2plan-a", "s2plan-A"), VALID.replace("\"analyze_plan\"", "\"unknown\""),
                "[]", "{}")) {
            assertThrows(CustomException.class, () -> parse(body), body);
        }
        assertThrows(CustomException.class, () -> AnalyzePlanRequestParser.parse(new ByteArrayInputStream(new byte[]{(byte)0xff})));
    }

    @Test
    void recognizesLegacyShapesWithoutTighteningThemOrCreatingAnExecutor() {
        for (String kind : List.of("ingest", "revalidate", "project")) {
            var failure = assertThrows(CustomException.class, () -> parse("{\"kind\":\"" + kind
                    + "\",\"reason\":\"운영 확인\",\"sourceId\":null,\"candidateIds\":[],\"futureProperty\":true}"));
            assertEquals("SOURCE_UNAVAILABLE", failure.getErrorCode().name());
        }
    }

    @Test
    void stopsReadingAtTheFiniteByteBoundaryEvenWhenTheStreamDoesNotEnd() throws Exception {
        class Endless extends InputStream {
            int read;
            @Override public int read() { read++; return ' '; }
        }
        Endless source = new Endless();
        assertThrows(CustomException.class, () -> AnalyzePlanRequestParser.parse(source));
        assertEquals(AnalyzePlanRequestParser.MAX_BYTES + 1, source.read);
        String padded = VALID + " ".repeat(AnalyzePlanRequestParser.MAX_BYTES - VALID.getBytes(StandardCharsets.UTF_8).length);
        assertEquals("운영 확인", parse(padded).reason());
        assertThrows(CustomException.class, () -> parse(padded + " "));
    }

    private static AnalyzePlanCommand parse(String body) throws Exception {
        return AnalyzePlanRequestParser.parse(new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8)));
    }
}
