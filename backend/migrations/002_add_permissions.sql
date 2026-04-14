-- Migration: Add permissions column to users table
-- Adds a JSON column for fine-grained module-level permissions

ALTER TABLE users ADD COLUMN permissions JSON NULL DEFAULT NULL AFTER is_active;
