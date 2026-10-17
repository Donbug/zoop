package com.zoop.admin.auth.service;

import com.zoop.admin.auth.dto.AdminLoginRequest;
import com.zoop.admin.auth.repository.AdminAuthRepository;
import com.zoop.auth.service.AuthRateLimiter;
import com.zoop.auth.service.CredentialPolicy;
import com.zoop.auth.service.PasswordHashService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AdminLoginService {
    private final AdminAuthRepository admins;
    private final CredentialPolicy credentials;
    private final PasswordHashService passwords;
    private final AuthRateLimiter rates;
    private final AdminSessionService sessions;
    private final AdminAuthAuditService audit;

    public AdminLoginService(AdminAuthRepository admins, CredentialPolicy credentials,
            PasswordHashService passwords, AuthRateLimiter rates, AdminSessionService sessions,
            AdminAuthAuditService audit) {
        this.admins = admins;
        this.credentials = credentials;
        this.passwords = passwords;
        this.rates = rates;
        this.sessions = sessions;
        this.audit = audit;
    }

    @Transactional
    public AdminSessionService.IssuedSession login(AdminLoginRequest request,
            String previousToken, String requestId) {
        if (request == null || request.email() == null || request.password() == null) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        var email = credentials.email(request.email());
        rates.checkAdminLoginEmailFailures(email.key());
        var admin = admins.findAccountByEmailKey(email.key());
        String hash = admin.map(row -> row.passwordHash()).orElse(null);
        boolean passwordMatches = passwords.matchesOrDummy(request.password(), hash);
        if (!passwordMatches || admin.isEmpty()) {
            rates.recordAdminLoginFailure(email.key());
            audit.loginFailed(requestId, "invalid_credentials");
            throw new CustomException(ErrorCode.INVALID_CREDENTIALS);
        }
        var account = admin.orElseThrow();
        if (!"active".equals(account.status()) || !"admin".equals(account.role())) {
            rates.recordAdminLoginFailure(email.key());
            audit.loginFailed(requestId, "account_blocked");
            throw new CustomException(ErrorCode.MEMBER_BLOCKED);
        }
        var issued = sessions.issue(account.id(), account.email(), account.displayName(),
                previousToken, requestId, audit);
        rates.clearAdminLoginFailures(email.key());
        return issued;
    }
}
