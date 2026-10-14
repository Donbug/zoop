package com.zoop.auth.service;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Service;

/** Entry point for signup/login before credentials are checked or sessions are created. */
@Service
public class AuthAttemptGate {
    private final AuthOriginPolicy origins;
    private final AuthClientIpResolver clientIps;
    private final AuthRateLimiter rates;

    public AuthAttemptGate(AuthOriginPolicy origins, AuthClientIpResolver clientIps,
            AuthRateLimiter rates) {
        this.origins = origins;
        this.clientIps = clientIps;
        this.rates = rates;
    }

    public EmailAddress signup(HttpServletRequest request, String rawEmail) {
        origins.verify(request);
        String ip = clientIps.resolve(request);
        try {
            EmailAddress email = EmailAddress.parse(rawEmail);
            rates.recordSignupAttempt(ip, email.key());
            return email;
        } catch (CustomException exception) {
            if (exception.getErrorCode() != ErrorCode.INVALID_REQUEST) {
                throw exception;
            }
            rates.recordSignupIpAttempt(ip);
            throw exception;
        }
    }

    public EmailAddress login(HttpServletRequest request, String rawEmail) {
        origins.verify(request);
        String ip = clientIps.resolve(request);
        try {
            EmailAddress email = EmailAddress.parse(rawEmail);
            rates.recordLoginAttempt(ip, email.key());
            return email;
        } catch (CustomException exception) {
            if (exception.getErrorCode() != ErrorCode.INVALID_REQUEST) {
                throw exception;
            }
            rates.recordLoginIpAttempt(ip);
            throw exception;
        }
    }

    public void loginFailed(EmailAddress email) {
        rates.recordLoginFailure(email.key());
    }

    public void loginSucceeded(EmailAddress email) {
        rates.clearLoginFailures(email.key());
    }
}
