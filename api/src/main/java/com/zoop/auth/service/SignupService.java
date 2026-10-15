package com.zoop.auth.service;

import java.security.SecureRandom;
import java.time.Clock;
import java.util.Base64;

import com.zoop.auth.dto.SignupRequest;
import com.zoop.auth.repository.MemberAuthRepository;
import com.zoop.auth.repository.SignupTermsRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class SignupService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private final CredentialPolicy credentials;
    private final PasswordHashService passwords;
    private final SignupAgreementPolicy agreements;
    private final SignupTermsRepository terms;
    private final MemberAuthRepository members;
    private final MemberSessionService sessions;
    private final Clock clock;

    public SignupService(CredentialPolicy credentials, PasswordHashService passwords,
            SignupAgreementPolicy agreements, SignupTermsRepository terms,
            MemberAuthRepository members, MemberSessionService sessions, Clock clock) {
        this.credentials = credentials;
        this.passwords = passwords;
        this.agreements = agreements;
        this.terms = terms;
        this.members = members;
        this.sessions = sessions;
        this.clock = clock;
    }

    @Transactional
    public MemberSessionService.IssuedSession signup(SignupRequest request, EmailAddress email,
            String previousCookieToken, String requestId) {
        if (request == null || email == null) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        String displayName = credentials.displayName(request.displayName());
        credentials.newPassword(request.password());
        var now = clock.instant();
        var accepted = agreements.validate(request.agreements(), now);
        if (members.findByEmailKey(email.key()).isPresent()) {
            throw new CustomException(ErrorCode.EMAIL_TAKEN);
        }
        String passwordHash = passwords.hashNewPassword(request.password());

        String memberId = randomId();
        members.insertEmailMember(memberId, randomId(), email.value(), email.key(),
                displayName, passwordHash, now);
        for (SignupRequest.Agreement agreement : accepted) {
            terms.recordAgreement(memberId, agreement.id(), agreement.version(),
                    agreement.accepted(), now);
        }
        return sessions.issue(memberId, previousCookieToken, requestId);
    }

    private static String randomId() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
