package com.zoop.admin.transcripts;

import com.zoop.auth.service.CsrfKeyRing;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.HexFormat;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** FS066-03: a dedicated deployment secret keeps pseudonyms stable across CSRF key rotation. */
@Component
public final class TranscriptPseudonym {
    private static final Logger log = LoggerFactory.getLogger(TranscriptPseudonym.class);
    private static final String PURPOSE = "admin-transcript-user-v1";
    private final byte[] dedicatedKey;
    private final CsrfKeyRing csrf;

    public TranscriptPseudonym(@Value("${zoop.admin.transcript-pseudonym-key:}") String configuredKey,
            CsrfKeyRing csrf) {
        this.csrf = csrf;
        if (configuredKey == null || configuredKey.isBlank()) {
            dedicatedKey = null;
            log.warn("Dedicated transcript pseudonym key is not configured; using the CSRF key fallback");
        } else {
            dedicatedKey = configuredKey.getBytes(StandardCharsets.UTF_8);
            if (dedicatedKey.length < 32) throw new IllegalArgumentException("Invalid transcript pseudonym key configuration");
        }
    }

    public String forMember(String memberId) {
        byte[] payload = memberId.getBytes(StandardCharsets.UTF_8);
        byte[] digest;
        if (dedicatedKey == null) digest = csrf.sign(csrf.activeKeyId(), PURPOSE, payload).orElseThrow();
        else {
            try {
                Mac mac = Mac.getInstance("HmacSHA256");
                mac.init(new SecretKeySpec(dedicatedKey, "HmacSHA256"));
                mac.update(PURPOSE.getBytes(StandardCharsets.US_ASCII));
                mac.update((byte) 0);
                digest = mac.doFinal(payload);
            } catch (GeneralSecurityException error) {
                throw new IllegalStateException("Transcript pseudonym unavailable");
            }
        }
        return "user-" + HexFormat.of().formatHex(digest).substring(0, 20);
    }
}
