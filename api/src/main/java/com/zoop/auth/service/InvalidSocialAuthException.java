package com.zoop.auth.service;

/** A provider response failed authentication checks; intentionally carries no token or claim data. */
final class InvalidSocialAuthException extends RuntimeException {
    InvalidSocialAuthException() {
        super("Social authentication could not be verified", null, false, false);
    }
}
