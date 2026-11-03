package com.zoop.admin.transcripts;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

class TranscriptMaskerTest {
    private final TranscriptMasker masker = new TranscriptMasker();

    @ParameterizedTest
    @CsvSource({
            "fixture@example.test,email,[이메일]",
            "010-2345-6789,phone,[전화번호]",
            "010.2345.6789,phone,[전화번호]",
            "+82 10 2345 6789,phone,[전화번호]",
            "02-345-6789,phone,[전화번호]",
            "900101-1234567,rrn,[주민등록번호]",
            "4111-1111-1111-1111,card,[카드번호]",
            "123-456-789012,account,[계좌번호]",
            "12345678901234567890,account,[계좌번호]"
    })
    void masksEveryMinimumNumericAndEmailRule(String input, String kind, String expected) {
        var masked = masker.mask(input, null);
        assertEquals(expected, masked.text());
        assertEquals(java.util.Map.of(kind, 1), masked.counts());
        assertTrue(TranscriptMasker.containsSensitive(input));
    }

    @ParameterizedTest
    @CsvSource({"token", "access_token", "api_key", "%74oken", "X-Amz-Security-Token", "X-Amz-Signature"})
    void masksUrlQueryTokensBeforeTheirContents(String key) {
        var masked = masker.mask("https://example.test/path?" + key + "=secret-value&view=all", null);
        assertEquals("https://example.test/path?" + key + "=[토큰]&view=all", masked.text());
        assertEquals(java.util.Map.of("token", 1), masked.counts());
    }

    @Test void masksKnownOwnerIdentityAndCountsRepeatedOccurrences() {
        var owner = new TranscriptMasker.Owner("synthetic-owner", "fixture@example.test", "합성회원");
        var masked = masker.mask("합성회원 synthetic-owner fixture@example.test fixture@example.test", owner);
        assertEquals("[이름] [회원] [이메일] [이메일]", masked.text());
        assertEquals(java.util.Map.of("email", 2, "name", 1, "userId", 1), masked.counts());
    }

    @Test void preservesZeroAndOrdinaryTextWithoutInventingReplacements() {
        var masked = masker.mask("매출 0원, 자료를 확인해요.", null);
        assertEquals("매출 0원, 자료를 확인해요.", masked.text());
        assertTrue(masked.counts().isEmpty());
        assertThrows(IllegalArgumentException.class, () -> masker.mask(null, null));
    }

    @Test void aLongNonEmailRunDoesNotHideTheFollowingEmailOrAlterOrdinaryText() {
        String ordinary = "a".repeat(50_000);
        var masked = masker.mask(ordinary + " fixture@example.test", null);
        assertEquals(ordinary + " [이메일]", masked.text());
        assertEquals(java.util.Map.of("email", 1), masked.counts());
    }

    @Test void masksLongDottedDomainsWithoutRecursiveRegexGroups() {
        var masked = masker.mask("fixture@" + "sub.".repeat(10_000) + "test", null);
        assertEquals("[이메일]", masked.text());
        assertEquals(java.util.Map.of("email", 1), masked.counts());
    }
}
