package com.zoop.admin.transcripts;

import static org.junit.jupiter.api.Assertions.*;
import com.zoop.auth.service.CsrfKeyRing;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;

@ExtendWith(OutputCaptureExtension.class)
class TranscriptPseudonymTest {
    // Generated per test run. No dedicated deployment key is embedded in a fixture or log.
    private static String randomSecret() {
        byte[] bytes = new byte[32]; new SecureRandom().nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
    private static CsrfKeyRing keys(String active, String first, String second) {
        return new CsrfKeyRing(active, "first=" + first + ",second=" + second);
    }

    @Test void dedicatedKeyKeepsPseudonymsStableAcrossCsrfRotation(CapturedOutput output) {
        String secret = randomSecret(), first = randomSecret(), second = randomSecret();
        var before = new TranscriptPseudonym(secret, keys("first", first, second));
        var after = new TranscriptPseudonym(secret, keys("second", first, second));
        assertEquals(before.forMember("synthetic-member"), after.forMember("synthetic-member"));
        assertNotEquals(before.forMember("synthetic-member"), before.forMember("another-member"));
        assertNotEquals(before.forMember("synthetic-member"),
                new TranscriptPseudonym(randomSecret(), keys("first", first, second)).forMember("synthetic-member"));
        assertFalse(output.getAll().contains(secret));
    }

    @Test void emptySettingPreservesLegacySigningAndWarnsOnce(CapturedOutput output) {
        var csrf = keys("first", randomSecret(), randomSecret());
        var pseudonyms = new TranscriptPseudonym("", csrf);
        String member = "synthetic-member";
        String expected = "user-" + HexFormat.of().formatHex(csrf.sign(csrf.activeKeyId(), "admin-transcript-user-v1",
                member.getBytes(StandardCharsets.UTF_8)).orElseThrow()).substring(0, 20);
        assertEquals(expected, pseudonyms.forMember(member));
        assertEquals(expected, pseudonyms.forMember(member));
        assertEquals(1, output.getAll().split("Dedicated transcript pseudonym key is not configured", -1).length - 1);
    }

    @Test void shortDedicatedKeyFailsAtConstructionWithoutExposingItsValue(CapturedOutput output) {
        String secret = randomSecret().substring(0, 31);
        var error = assertThrows(IllegalArgumentException.class,
                () -> new TranscriptPseudonym(secret, keys("first", randomSecret(), randomSecret())));
        assertFalse(error.getMessage().contains(secret));
        assertFalse(output.getAll().contains(secret));
    }
}
