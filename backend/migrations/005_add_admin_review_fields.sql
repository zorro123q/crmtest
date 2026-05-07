-- Add unified administrator review fields for leads and opportunities.
-- Run after 004_add_scoring_and_archive_support.sql.

SET NAMES utf8mb4;

ALTER TABLE leads
    ADD COLUMN review_status VARCHAR(30) NOT NULL DEFAULT 'pending' AFTER is_active,
    ADD COLUMN review_by VARCHAR(36) NULL AFTER review_status,
    ADD COLUMN review_at DATETIME NULL AFTER review_by,
    ADD COLUMN review_remark TEXT NULL AFTER review_at;

UPDATE leads
SET review_status = CASE
    WHEN LOWER(COALESCE(status, '')) IN ('archived', 'invalid', 'disqualified') THEN 'rejected'
    WHEN LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.first_review_pass')), '')) IN ('否', 'no', 'n', 'false', '0', '不通过', 'fail', 'failed') THEN 'rejected'
    ELSE 'approved'
END;

UPDATE leads
SET is_active = IF(review_status = 'approved' AND LOWER(COALESCE(status, '')) <> 'archived', TRUE, FALSE);

ALTER TABLE opportunities
    ADD COLUMN review_status VARCHAR(30) NOT NULL DEFAULT 'pending' AFTER is_active,
    ADD COLUMN review_by VARCHAR(36) NULL AFTER review_status,
    ADD COLUMN review_at DATETIME NULL AFTER review_by,
    ADD COLUMN review_remark TEXT NULL AFTER review_at;

UPDATE opportunities
SET review_status = CASE
    WHEN LOWER(COALESCE(status, '')) = 'archived' THEN 'rejected'
    ELSE 'approved'
END;

UPDATE opportunities
SET is_active = IF(review_status = 'approved' AND LOWER(COALESCE(status, '')) <> 'archived', TRUE, FALSE);
