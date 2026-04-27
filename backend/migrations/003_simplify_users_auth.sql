-- Simplify legacy users table to username + password auth.

SET @db_name = DATABASE();

SET @has_password = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'password'
);

SET @has_hashed_pwd = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'hashed_pwd'
);

SET @rename_password_sql = IF(
    @has_password = 0 AND @has_hashed_pwd > 0,
    'ALTER TABLE users CHANGE COLUMN hashed_pwd password VARCHAR(255) NOT NULL',
    'SELECT 1'
);
PREPARE stmt FROM @rename_password_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE users MODIFY COLUMN username VARCHAR(100) NOT NULL;

SET @has_email = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'email'
);
SET @drop_email_sql = IF(@has_email > 0, 'ALTER TABLE users DROP COLUMN email', 'SELECT 1');
PREPARE stmt FROM @drop_email_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_role = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'role'
);
SET @drop_role_sql = IF(@has_role > 0, 'ALTER TABLE users DROP COLUMN role', 'SELECT 1');
PREPARE stmt FROM @drop_role_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_avatar_url = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'avatar_url'
);
SET @drop_avatar_url_sql = IF(@has_avatar_url > 0, 'ALTER TABLE users DROP COLUMN avatar_url', 'SELECT 1');
PREPARE stmt FROM @drop_avatar_url_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_is_active = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'is_active'
);
SET @drop_is_active_sql = IF(@has_is_active > 0, 'ALTER TABLE users DROP COLUMN is_active', 'SELECT 1');
PREPARE stmt FROM @drop_is_active_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_permissions = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'permissions'
);
SET @drop_permissions_sql = IF(@has_permissions > 0, 'ALTER TABLE users DROP COLUMN permissions', 'SELECT 1');
PREPARE stmt FROM @drop_permissions_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_idx_users_email = (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND INDEX_NAME = 'idx_users_email'
);

SET @drop_idx_users_email_sql = IF(
    @has_idx_users_email > 0,
    'DROP INDEX idx_users_email ON users',
    'SELECT 1'
);
PREPARE stmt FROM @drop_idx_users_email_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_idx_users_role = (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND INDEX_NAME = 'idx_users_role'
);

SET @drop_idx_users_role_sql = IF(
    @has_idx_users_role > 0,
    'DROP INDEX idx_users_role ON users',
    'SELECT 1'
);
PREPARE stmt FROM @drop_idx_users_role_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_unique_username = (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @db_name
      AND TABLE_NAME = 'users'
      AND INDEX_NAME = 'uk_users_username'
);

SET @add_unique_username_sql = IF(
    @has_unique_username = 0,
    'ALTER TABLE users ADD UNIQUE KEY uk_users_username (username)',
    'SELECT 1'
);
PREPARE stmt FROM @add_unique_username_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO users (id, username, password, created_at, updated_at)
SELECT '10000000-0000-4000-8000-000000000001', 'admin', '123456', CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6)
WHERE NOT EXISTS (SELECT 1 FROM users LIMIT 1);
