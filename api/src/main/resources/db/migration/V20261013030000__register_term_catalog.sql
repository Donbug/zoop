-- Register the required catalog before the approved bodies are inserted by
-- the following migration.
INSERT INTO terms (id, title, required, created_at)
VALUES
    ('service', '서비스 이용약관', true, CURRENT_TIMESTAMP),
    ('privacy', '개인정보 처리방침', true, CURRENT_TIMESTAMP);
