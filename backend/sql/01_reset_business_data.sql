-- Safe data reset for SalesPilot CRM.
-- Keeps table structures and metadata tables intact.
-- Clears old business/demo data that can interfere with auth verification and dashboard metrics.

START TRANSACTION;

DELETE FROM activities;
DELETE FROM opportunities;
DELETE FROM leads;
DELETE FROM contacts;
DELETE FROM accounts;

-- Legacy/demo analytics tables still exist in the database and can mislead manual verification.
DELETE FROM customer_internal_info;
DELETE FROM opportunity_funnel;
DELETE FROM performance_overview;

-- Keep only the reserved admin account; it will be reseeded in the next script.
DELETE FROM users WHERE username <> 'admin';

COMMIT;
