"""
Runtime schema patching for local development environments.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import engine
from app.services.crm_rules_service import DEFAULT_OPPORTUNITY_STAGE


USER_COLUMN_DEFINITIONS = {
    "is_admin": "TINYINT(1) NOT NULL DEFAULT 0 AFTER password",
}

LEAD_COLUMN_DEFINITIONS = {
    "card_score": "INT NOT NULL DEFAULT 0 AFTER score",
    "card_level": "VARCHAR(1) NOT NULL DEFAULT 'E' AFTER card_score",
    "is_active": "TINYINT(1) NOT NULL DEFAULT 1 AFTER converted_to",
    "review_status": "VARCHAR(30) NOT NULL DEFAULT 'pending' AFTER is_active",
    "review_by": "VARCHAR(36) NULL AFTER review_status",
    "review_at": "DATETIME NULL AFTER review_by",
    "review_remark": "TEXT NULL AFTER review_at",
    "industry": "VARCHAR(100) NULL AFTER review_remark",
    "industry_rank": "VARCHAR(100) NULL AFTER industry",
    "scene": "VARCHAR(120) NULL AFTER industry_rank",
    "budget": "VARCHAR(100) NULL AFTER scene",
    "labor_cost": "VARCHAR(100) NULL AFTER budget",
    "daily_calls": "VARCHAR(100) NULL AFTER labor_cost",
    "leader_owner": "VARCHAR(100) NULL AFTER daily_calls",
    "lowest_price": "VARCHAR(50) NULL AFTER leader_owner",
    "initiator_department": "VARCHAR(100) NULL AFTER lowest_price",
    "competitor": "VARCHAR(100) NULL AFTER initiator_department",
    "bidding_type": "VARCHAR(100) NULL AFTER competitor",
    "has_ai_project": "VARCHAR(50) NULL AFTER bidding_type",
    "customer_service_size": "VARCHAR(100) NULL AFTER has_ai_project",
    "region": "VARCHAR(100) NULL AFTER customer_service_size",
    "score_detail_json": "JSON NULL AFTER region",
}

OPPORTUNITY_COLUMN_DEFINITIONS = {
    "status": "VARCHAR(50) NOT NULL DEFAULT 'new' AFTER stage",
    "card_score": "INT NOT NULL DEFAULT 0 AFTER source",
    "card_level": "VARCHAR(1) NOT NULL DEFAULT 'E' AFTER card_score",
    "is_active": "TINYINT(1) NOT NULL DEFAULT 1 AFTER card_level",
    "review_status": "VARCHAR(30) NOT NULL DEFAULT 'pending' AFTER is_active",
    "review_by": "VARCHAR(36) NULL AFTER review_status",
    "review_at": "DATETIME NULL AFTER review_by",
    "review_remark": "TEXT NULL AFTER review_at",
    "industry": "VARCHAR(100) NULL AFTER review_remark",
    "industry_rank": "VARCHAR(100) NULL AFTER industry",
    "scene": "VARCHAR(120) NULL AFTER industry_rank",
    "budget": "VARCHAR(100) NULL AFTER scene",
    "labor_cost": "VARCHAR(100) NULL AFTER budget",
    "daily_calls": "VARCHAR(100) NULL AFTER labor_cost",
    "leader_owner": "VARCHAR(100) NULL AFTER daily_calls",
    "lowest_price": "VARCHAR(50) NULL AFTER leader_owner",
    "initiator_department": "VARCHAR(100) NULL AFTER lowest_price",
    "competitor": "VARCHAR(100) NULL AFTER initiator_department",
    "bidding_type": "VARCHAR(100) NULL AFTER competitor",
    "has_ai_project": "VARCHAR(50) NULL AFTER bidding_type",
    "customer_service_size": "VARCHAR(100) NULL AFTER has_ai_project",
    "region": "VARCHAR(100) NULL AFTER customer_service_size",

    # 新增：客户商机管理表正式业务列
    "customer_name": "VARCHAR(255) NULL AFTER custom_fields",
    "customer_type": "VARCHAR(50) NULL AFTER customer_name",
    "requirement_desc": "TEXT NULL AFTER customer_type",
    "product_name": "VARCHAR(255) NULL AFTER requirement_desc",
    "estimated_cycle": "VARCHAR(100) NULL AFTER product_name",
    "opportunity_level": "VARCHAR(10) NULL AFTER estimated_cycle",
    "project_date": "VARCHAR(100) NULL AFTER opportunity_level",
    "project_members": "TEXT NULL AFTER project_date",
    "solution_communication": "TEXT NULL AFTER project_members",
    "poc_status": "TEXT NULL AFTER solution_communication",
    "key_person_approved": "VARCHAR(20) NULL AFTER poc_status",
    "bid_probability": "VARCHAR(10) NULL AFTER key_person_approved",
    "contract_negotiation": "TEXT NULL AFTER bid_probability",
    "project_type": "VARCHAR(100) NULL AFTER contract_negotiation",
    "contract_signed": "VARCHAR(20) NULL AFTER project_type",
    "handoff_completed": "VARCHAR(20) NULL AFTER contract_signed",

    "score_detail_json": "JSON NULL AFTER handoff_completed",
}

LEAD_FIXUP_STATEMENTS = [
    """
    UPDATE leads
    SET status = CASE
        WHEN LOWER(status) = 'new' THEN 'new'
        WHEN LOWER(status) IN ('working', 'nurturing', 'follow_up') THEN 'follow_up'
        WHEN LOWER(status) = 'converted' THEN 'converted'
        WHEN LOWER(status) IN ('disqualified', 'invalid') THEN 'invalid'
        WHEN LOWER(status) = 'archived' THEN 'archived'
        ELSE 'new'
    END
    """,
    """
    UPDATE leads
    SET card_score = COALESCE(score, 0)
    WHERE card_score = 0 AND score IS NOT NULL
    """,
    """
    UPDATE leads
    SET card_level = CASE
        WHEN card_score < 20 THEN 'E'
        WHEN card_score < 40 THEN 'D'
        WHEN card_score < 60 THEN 'C'
        WHEN card_score < 70 THEN 'B'
        ELSE 'A'
    END
    """,
    """
    UPDATE leads
    SET is_active = IF(review_status = 'approved' AND status <> 'archived', TRUE, FALSE),
        score_detail_json = COALESCE(score_detail_json, JSON_OBJECT())
    """,
]

OPPORTUNITY_FIXUP_STATEMENTS = [
    """
    UPDATE opportunities
    SET status = CASE
        WHEN LOWER(status) = 'archived' THEN 'archived'
        WHEN COALESCE(probability, 0) >= 100 THEN 'won'
        WHEN COALESCE(probability, 20) = 0 THEN 'lost'
        WHEN COALESCE(probability, 20) > 20 THEN 'follow_up'
        ELSE 'new'
    END
    """,
    """
    UPDATE opportunities
    SET card_level = CASE
        WHEN card_score < 20 THEN 'E'
        WHEN card_score < 40 THEN 'D'
        WHEN card_score < 60 THEN 'C'
        WHEN card_score < 70 THEN 'B'
        ELSE 'A'
    END
    """,
    """
    UPDATE opportunities
    SET
        customer_name = COALESCE(
            NULLIF(customer_name, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.customer_name')), ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.company')), '')
        ),
        customer_type = COALESCE(
            NULLIF(customer_type, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.customer_type')), '')
        ),
        requirement_desc = COALESCE(
            NULLIF(requirement_desc, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.requirement_desc')), ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.notes')), '')
        ),
        product_name = COALESCE(
            NULLIF(product_name, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.product_name')), '')
        ),
        estimated_cycle = COALESCE(
            NULLIF(estimated_cycle, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.estimated_cycle')), '')
        ),
        opportunity_level = COALESCE(
            NULLIF(opportunity_level, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.opportunity_level')), '')
        ),
        project_date = COALESCE(
            NULLIF(project_date, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.project_date')), '')
        ),
        project_members = COALESCE(
            NULLIF(project_members, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.project_members')), '')
        ),
        solution_communication = COALESCE(
            NULLIF(solution_communication, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.solution_communication')), '')
        ),
        poc_status = COALESCE(
            NULLIF(poc_status, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.poc_status')), '')
        ),
        key_person_approved = COALESCE(
            NULLIF(key_person_approved, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.key_person_approved')), '')
        ),
        bid_probability = COALESCE(
            NULLIF(bid_probability, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.bid_probability')), '')
        ),
        contract_negotiation = COALESCE(
            NULLIF(contract_negotiation, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.contract_negotiation')), '')
        ),
        project_type = COALESCE(
            NULLIF(project_type, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.project_type')), '')
        ),
        contract_signed = COALESCE(
            NULLIF(contract_signed, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.contract_signed')), '')
        ),
        handoff_completed = COALESCE(
            NULLIF(handoff_completed, ''),
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.handoff_completed')), '')
        )
    """,
    """
    UPDATE opportunities
    SET is_active = IF(review_status = 'approved' AND status <> 'archived', TRUE, FALSE),
        score_detail_json = COALESCE(score_detail_json, JSON_OBJECT())
    """,
]


LEAD_REVIEW_INITIALIZE_STATEMENTS = [
    """
    UPDATE leads
    SET review_status = CASE
        WHEN LOWER(COALESCE(status, '')) IN ('archived', 'invalid', 'disqualified') THEN 'rejected'
        WHEN LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(custom_fields, '$.first_review_pass')), '')) IN ('否', 'no', 'n', 'false', '0', '不通过', 'fail', 'failed') THEN 'rejected'
        ELSE 'approved'
    END
    WHERE review_status = 'pending'
    """,
]

OPPORTUNITY_REVIEW_INITIALIZE_STATEMENTS = [
    """
    UPDATE opportunities
    SET review_status = CASE
        WHEN LOWER(COALESCE(status, '')) = 'archived' THEN 'rejected'
        ELSE 'approved'
    END
    WHERE review_status = 'pending'
    """,
]


async def _show_columns(conn, table_name: str) -> dict[str, str]:
    rows = (await conn.execute(text(f"SHOW COLUMNS FROM {table_name}"))).all()
    return {str(row[0]): str(row[1]).lower() for row in rows}


async def _add_missing_columns(conn, table_name: str, existing: dict[str, str], definitions: dict[str, str]) -> set[str]:
    added: set[str] = set()
    for column_name, definition in definitions.items():
        if column_name not in existing:
            await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
            added.add(column_name)
    return added


async def ensure_runtime_schema():
    async with engine.begin() as conn:
        user_columns = await _show_columns(conn, "users")
        await _add_missing_columns(conn, "users", user_columns, USER_COLUMN_DEFINITIONS)
        await conn.execute(text("UPDATE users SET is_admin = 1 WHERE username = 'admin'"))

        lead_columns = await _show_columns(conn, "leads")
        if lead_columns.get("status", "").startswith("enum("):
            await conn.execute(text("ALTER TABLE leads MODIFY COLUMN status VARCHAR(50) NOT NULL DEFAULT 'new'"))
        added_lead_columns = await _add_missing_columns(conn, "leads", lead_columns, LEAD_COLUMN_DEFINITIONS)
        if "review_status" in added_lead_columns:
            for statement in LEAD_REVIEW_INITIALIZE_STATEMENTS:
                await conn.execute(text(statement))
        for statement in LEAD_FIXUP_STATEMENTS:
            await conn.execute(text(statement))

        opportunity_columns = await _show_columns(conn, "opportunities")
        await conn.execute(
            text(
                f"ALTER TABLE opportunities MODIFY COLUMN stage VARCHAR(100) "
                f"NOT NULL DEFAULT '{DEFAULT_OPPORTUNITY_STAGE}'"
            )
        )
        added_opportunity_columns = await _add_missing_columns(
            conn,
            "opportunities",
            opportunity_columns,
            OPPORTUNITY_COLUMN_DEFINITIONS,
        )
        if "review_status" in added_opportunity_columns:
            for statement in OPPORTUNITY_REVIEW_INITIALIZE_STATEMENTS:
                await conn.execute(text(statement))
        for statement in OPPORTUNITY_FIXUP_STATEMENTS:
            await conn.execute(text(statement))
