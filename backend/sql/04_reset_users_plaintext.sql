-- Reset the users table to plain-text password mode.
-- This script keeps table structure intact, clears existing users,
-- releases FK ownership references, and recreates the default admin.

START TRANSACTION;

-- Release FK references before deleting users.
UPDATE activities SET owner_id = NULL WHERE owner_id IS NOT NULL;
UPDATE opportunities SET owner_id = NULL WHERE owner_id IS NOT NULL;
UPDATE leads SET owner_id = NULL WHERE owner_id IS NOT NULL;
UPDATE contacts SET owner_id = NULL WHERE owner_id IS NOT NULL;
UPDATE accounts SET owner_id = NULL WHERE owner_id IS NOT NULL;

DELETE FROM users;

INSERT INTO users (
    id,
    username,
    password,
    created_at,
    updated_at
)
VALUES (
    '10000000-0000-4000-8000-000000000001',
    'admin',
    '123456',
    CURRENT_TIMESTAMP(6),
    CURRENT_TIMESTAMP(6)
);

COMMIT;
