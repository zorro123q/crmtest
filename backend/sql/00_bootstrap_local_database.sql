-- Bootstrap a local MySQL database/user for SalesPilot CRM development.
-- Run this file with a MySQL admin account before starting the backend
-- if `backend/.env` still uses `salespilot / changeme123`.

SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS salespilot_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'salespilot'@'localhost' IDENTIFIED BY 'changeme123';
CREATE USER IF NOT EXISTS 'salespilot'@'127.0.0.1' IDENTIFIED BY 'changeme123';

ALTER USER 'salespilot'@'localhost' IDENTIFIED BY 'changeme123';
ALTER USER 'salespilot'@'127.0.0.1' IDENTIFIED BY 'changeme123';

GRANT ALL PRIVILEGES ON salespilot_db.* TO 'salespilot'@'localhost';
GRANT ALL PRIVILEGES ON salespilot_db.* TO 'salespilot'@'127.0.0.1';

FLUSH PRIVILEGES;
