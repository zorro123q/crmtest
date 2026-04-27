-- Default admin seed for the simplified auth flow.
-- Username: admin
-- Password: 123456
-- Password storage mode: plain text

INSERT INTO users (id, username, password, created_at, updated_at)
VALUES (
    '10000000-0000-4000-8000-000000000001',
    'admin',
    '123456',
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
)
ON DUPLICATE KEY UPDATE
    id = VALUES(id),
    password = VALUES(password),
    updated_at = CURRENT_TIMESTAMP(6);
