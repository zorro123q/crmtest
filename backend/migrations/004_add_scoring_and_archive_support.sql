-- Add scoring dimensions, archive support, and report fields for leads/opportunities.
-- This migration targets databases that are still on the original 001 schema.

SET NAMES utf8mb4;

ALTER TABLE leads
    MODIFY COLUMN status VARCHAR(50) NOT NULL DEFAULT 'new',
    ADD COLUMN card_score INT NOT NULL DEFAULT 0 AFTER score,
    ADD COLUMN card_level VARCHAR(1) NOT NULL DEFAULT 'E' AFTER card_score,
    ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE AFTER converted_to,
    ADD COLUMN industry VARCHAR(100) NULL AFTER is_active,
    ADD COLUMN industry_rank VARCHAR(100) NULL AFTER industry,
    ADD COLUMN scene VARCHAR(120) NULL AFTER industry_rank,
    ADD COLUMN budget VARCHAR(100) NULL AFTER scene,
    ADD COLUMN labor_cost VARCHAR(100) NULL AFTER budget,
    ADD COLUMN daily_calls VARCHAR(100) NULL AFTER labor_cost,
    ADD COLUMN leader_owner VARCHAR(100) NULL AFTER daily_calls,
    ADD COLUMN lowest_price VARCHAR(50) NULL AFTER leader_owner,
    ADD COLUMN initiator_department VARCHAR(100) NULL AFTER lowest_price,
    ADD COLUMN competitor VARCHAR(100) NULL AFTER initiator_department,
    ADD COLUMN bidding_type VARCHAR(100) NULL AFTER competitor,
    ADD COLUMN has_ai_project VARCHAR(50) NULL AFTER bidding_type,
    ADD COLUMN customer_service_size VARCHAR(100) NULL AFTER has_ai_project,
    ADD COLUMN region VARCHAR(100) NULL AFTER customer_service_size,
    ADD COLUMN score_detail_json JSON NULL AFTER region;

UPDATE leads
SET status = CASE
    WHEN LOWER(status) = 'new' THEN 'new'
    WHEN LOWER(status) IN ('working', 'nurturing', 'follow_up') THEN 'follow_up'
    WHEN LOWER(status) = 'converted' THEN 'converted'
    WHEN LOWER(status) IN ('disqualified', 'invalid') THEN 'invalid'
    WHEN LOWER(status) = 'archived' THEN 'archived'
    ELSE 'new'
END;

UPDATE leads
SET card_score = COALESCE(score, 0)
WHERE score IS NOT NULL;

UPDATE leads
SET card_level = CASE
    WHEN card_score < 20 THEN 'E'
    WHEN card_score < 40 THEN 'D'
    WHEN card_score < 60 THEN 'C'
    WHEN card_score < 70 THEN 'B'
    ELSE 'A'
END,
    is_active = IF(status = 'archived', FALSE, TRUE),
    score_detail_json = COALESCE(score_detail_json, JSON_OBJECT());

ALTER TABLE opportunities
    MODIFY COLUMN stage VARCHAR(100) NOT NULL DEFAULT '初步接触',
    ADD COLUMN status VARCHAR(50) NOT NULL DEFAULT 'new' AFTER stage,
    ADD COLUMN card_score INT NOT NULL DEFAULT 0 AFTER source,
    ADD COLUMN card_level VARCHAR(1) NOT NULL DEFAULT 'E' AFTER card_score,
    ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE AFTER card_level,
    ADD COLUMN industry VARCHAR(100) NULL AFTER is_active,
    ADD COLUMN industry_rank VARCHAR(100) NULL AFTER industry,
    ADD COLUMN scene VARCHAR(120) NULL AFTER industry_rank,
    ADD COLUMN budget VARCHAR(100) NULL AFTER scene,
    ADD COLUMN labor_cost VARCHAR(100) NULL AFTER budget,
    ADD COLUMN daily_calls VARCHAR(100) NULL AFTER labor_cost,
    ADD COLUMN leader_owner VARCHAR(100) NULL AFTER daily_calls,
    ADD COLUMN lowest_price VARCHAR(50) NULL AFTER leader_owner,
    ADD COLUMN initiator_department VARCHAR(100) NULL AFTER lowest_price,
    ADD COLUMN competitor VARCHAR(100) NULL AFTER initiator_department,
    ADD COLUMN bidding_type VARCHAR(100) NULL AFTER competitor,
    ADD COLUMN has_ai_project VARCHAR(50) NULL AFTER bidding_type,
    ADD COLUMN customer_service_size VARCHAR(100) NULL AFTER has_ai_project,
    ADD COLUMN region VARCHAR(100) NULL AFTER customer_service_size,
    ADD COLUMN score_detail_json JSON NULL AFTER custom_fields;

UPDATE opportunities
SET status = CASE
    WHEN COALESCE(probability, 0) >= 100 THEN 'won'
    WHEN COALESCE(probability, 20) = 0 THEN 'lost'
    WHEN COALESCE(probability, 20) > 20 THEN 'follow_up'
    ELSE 'new'
END,
    card_level = CASE
        WHEN card_score < 20 THEN 'E'
        WHEN card_score < 40 THEN 'D'
        WHEN card_score < 60 THEN 'C'
        WHEN card_score < 70 THEN 'B'
        ELSE 'A'
    END,
    is_active = TRUE,
    score_detail_json = COALESCE(score_detail_json, JSON_OBJECT());
