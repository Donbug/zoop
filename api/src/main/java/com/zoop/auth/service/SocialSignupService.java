package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Optional;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import com.zoop.auth.dto.SocialSignupRequest;
import com.zoop.auth.repository.MemberAuthRepository;
import com.zoop.auth.repository.OAuthPendingRepository;
import com.zoop.auth.repository.OAuthPendingRow;
import com.zoop.auth.repository.SignupTermsRepository;
import com.zoop.auth.repository.SocialIdentityRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Completes a social signup from a one-time, verified provider result and explicit terms consent. */
@Service
public class SocialSignupService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private final OAuthPendingRepository pending;
    private final SignupAgreementPolicy agreements;
    private final SignupTermsRepository terms;
    private final MemberAuthRepository members;
    private final SocialIdentityRepository identities;
    private final CredentialPolicy credentials;
    private final MemberSessionService sessions;
    private final ObjectMapper mapper;
    private final Clock clock;

    public SocialSignupService(OAuthPendingRepository pending, SignupAgreementPolicy agreements,
            SignupTermsRepository terms, MemberAuthRepository members, SocialIdentityRepository identities,
            CredentialPolicy credentials, MemberSessionService sessions, ObjectMapper mapper, Clock clock) {
        this.pending = pending;
        this.agreements = agreements;
        this.terms = terms;
        this.members = members;
        this.identities = identities;
        this.credentials = credentials;
        this.sessions = sessions;
        this.mapper = mapper;
        this.clock = clock;
    }

    /** Empty result means the verified address/identity became associated with another account. */
    @Transactional
    public Optional<MemberSessionService.IssuedSession> signup(SocialSignupRequest request,
            String pendingCookie, String previousSessionCookie, String requestId) {
        if (request == null || !validToken(pendingCookie)) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        Instant now = clock.instant();
        String cookieHash = hash(pendingCookie);
        try {
            OAuthPendingRow consumed = pending.consumeConsent(cookieHash, now).orElse(null);
            if (consumed == null || !cookieHash.equals(consumed.tokenHash())) {
                throw new CustomException(ErrorCode.ACCESS_DENIED);
            }
            JsonNode flow = parse(consumed.authFlow());
            if (!validFlow(flow)) throw new CustomException(ErrorCode.ACCESS_DENIED);

            String displayName = credentials.displayName(request.displayName());
            var accepted = agreements.validate(request.agreements(), now);
            EmailAddress email;
            try {
                email = EmailAddress.parse(text(flow, "email"));
            } catch (CustomException exception) {
                throw new CustomException(ErrorCode.ACCESS_DENIED);
            }
            String provider = text(flow, "provider");
            String subject = text(flow, "providerSubject");
            if (members.findByEmailKey(email.key()).isPresent()
                    || identities.findByProviderSubject(provider, subject).isPresent()) {
                return Optional.empty();
            }

            String memberId = randomToken();
            boolean inserted = members.insertSocialMember(memberId, randomToken(), email.value(), email.key(),
                    displayName, provider, now);
            if (!inserted) return Optional.empty();
            for (var agreement : accepted) {
                terms.recordAgreement(memberId, agreement.id(), agreement.version(), agreement.accepted(), now);
            }
            try {
                identities.insert(randomToken(), memberId, provider, subject, now);
            } catch (DuplicateKeyException exception) {
                throw new CustomException(ErrorCode.SOCIAL_LINK_REQUIRED, exception);
            }
            return Optional.of(sessions.issue(memberId, previousSessionCookie, requestId));
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private boolean validFlow(JsonNode flow) {
        String provider = text(flow, "provider");
        String subject = text(flow, "providerSubject");
        String stateHash = text(flow, "stateHash");
        return flow != null && flow.isObject() && flow.path("schemaVersion").asInt() == 1
                && "consent_pending".equals(text(flow, "phase"))
                && ("google".equals(provider) || "kakao".equals(provider))
                && subject != null && !subject.isBlank() && subject.length() <= 512
                && stateHash != null && stateHash.matches("[0-9a-f]{64}")
                && flow.path("emailVerified").isBoolean() && flow.path("emailVerified").asBoolean()
                && text(flow, "email") != null;
    }

    private JsonNode parse(String json) {
        try { return mapper.readTree(json); }
        catch (JacksonException exception) { return null; }
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node == null ? null : node.get(field);
        return value == null || !value.isString() ? null : value.asString();
    }

    private static boolean validToken(String token) {
        return token != null && token.matches("[A-Za-z0-9_-]{43}");
    }

    private static String randomToken() {
        byte[] bytes = new byte[32]; RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static String hash(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.US_ASCII)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 unavailable", exception);
        }
    }
}
