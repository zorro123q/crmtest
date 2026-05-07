-- Add persistent multi-admin support.

SET @has_is_admin = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'is_admin'
);

SET @add_is_admin_sql = IF(
    @has_is_admin = 0,
    'ALTER TABLE users ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0 AFTER password',
    'SELECT 1'
);
PREPARE stmt FROM @add_is_admin_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE users
SET is_admin = 1
WHERE username = 'admin';
