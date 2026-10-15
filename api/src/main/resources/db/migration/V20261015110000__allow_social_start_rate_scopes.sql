ALTER TABLE auth_rate_events DROP CONSTRAINT ck_auth_rate_events_scope;
ALTER TABLE auth_rate_events ADD CONSTRAINT ck_auth_rate_events_scope CHECK (scope IN (
    'signup_ip', 'signup_email', 'login_ip', 'login_email_failure',
    'social_start_ip', 'social_start_browser'));
