package com.zoop.auth.service;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Service;

/** Entry point for signup/login before credentials are checked or sessions are created. */
@Service
public class AuthAttemptGate {
    private final AuthOriginPolicy origins;
    private final AuthRateLimiter rates;

    public AuthAttemptGate(AuthOriginPolicy origins, AuthRateLimiter rates) {
        this.origins = origins;
        this.rates = rates;
    }

    public EmailAddress signup(HttpServletRequest request, String rawEmail) {
        origins.verify(request);
        EmailAddress email = EmailAddress.parse(rawEmail);
        rates.recordSignupEmailAttempt(email.key());
        return email;
    }

    public EmailAddress login(HttpServletRequest request, String rawEmail) {
        origins.verify(request);
        EmailAddress email = EmailAddress.parse(rawEmail);
        rates.checkLoginEmailFailures(email.key());
        return email;
    }

    public void loginFailed(EmailAddress email) {
        rates.recordLoginFailure(email.key());
    }

    public void loginSucceeded(EmailAddress email) {
        rates.clearLoginFailures(email.key());
    }
}
