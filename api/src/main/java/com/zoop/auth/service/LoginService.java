package com.zoop.auth.service;

import com.zoop.auth.repository.MemberAuthRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class LoginService {
    private final MemberAuthRepository members;
    private final PasswordHashService passwords;
    private final MemberSessionService sessions;
    private final AuthAttemptGate attempts;

    public LoginService(MemberAuthRepository members, PasswordHashService passwords,
            MemberSessionService sessions, AuthAttemptGate attempts) {
        this.members = members;
        this.passwords = passwords;
        this.sessions = sessions;
        this.attempts = attempts;
    }

    @Transactional
    public MemberSessionService.IssuedSession login(EmailAddress email, String password,
            String previousCookieToken, String requestId) {
        if (email == null || password == null) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        var member = members.findByEmailKey(email.key());
        if (!passwords.matchesOrDummy(password,
                member.map(row -> row.passwordHash()).orElse(null))) {
            attempts.loginFailed(email);
            throw new CustomException(ErrorCode.INVALID_CREDENTIALS);
        }
        var existing = member.orElseThrow();
        if (!"active".equals(existing.status())) {
            throw new CustomException(ErrorCode.MEMBER_BLOCKED);
        }
        var issued = sessions.issue(existing.id(), previousCookieToken, requestId);
        attempts.loginSucceeded(email);
        return issued;
    }
}
