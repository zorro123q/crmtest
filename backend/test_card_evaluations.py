import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.card_evaluations import evaluate_card_view
from app.schemas import CardEvaluateRequest
from app.services.card_evaluation_service import merge_dimensions
from app.services.scoring_service import calculate_card_score, get_scoring_field_keys, scoring_options_payload


class ScoringServiceTests(unittest.TestCase):
    def test_b_card_uses_independent_field_set(self):
        field_keys = get_scoring_field_keys("B")

        self.assertEqual(len(field_keys), 11)
        self.assertIn("customer_relationship", field_keys)
        self.assertIn("poc_result", field_keys)
        self.assertNotIn("industry", field_keys)
        self.assertNotIn("bidding_type", field_keys)

    def test_b_card_total_score_and_grade_follow_new_model(self):
        result = calculate_card_score(
            "B",
            {
                "customer_relationship": "old_customer",
                "requirement_clarity": "clear",
                "budget_level": "enough",
                "deal_cycle": "short",
                "opportunity_level": "A",
                "internal_review_status": "passed",
                "poc_result": "success",
                "key_person_acceptance": "full",
                "initiator_department": "core_business",
                "competition_status": "no_competitor",
                "service_team_size": "large",
            },
        )

        self.assertEqual(result.total_score, 100)
        self.assertEqual(result.card_level, "A")

    def test_b_card_grade_has_no_e(self):
        result = calculate_card_score(
            "B",
            {
                "customer_relationship": "new_customer_other",
                "opportunity_level": "D",
            },
        )

        self.assertEqual(result.total_score, 2.5)
        self.assertEqual(result.card_level, "D")

    def test_b_scoring_options_payload_returns_new_dimensions(self):
        fields = scoring_options_payload("B")
        field_names = [item["field"] for item in fields]

        self.assertEqual(len(fields), 11)
        self.assertIn("competition_status", field_names)
        self.assertIn("service_team_size", field_names)
        self.assertNotIn("industry", field_names)


class MergeDimensionsTests(unittest.TestCase):
    def test_manual_values_override_ai_and_ai_fills_gaps_for_b_card(self):
        merged, sources = merge_dimensions(
            ai_dimensions={
                "budget_level": "enough",
                "service_team_size": "medium",
            },
            manual_dimensions={
                "budget_level": "low",
                "customer_relationship": "old_customer",
            },
            card_type="B",
        )

        self.assertEqual(merged["budget_level"], "low")
        self.assertEqual(merged["service_team_size"], "medium")
        self.assertEqual(merged["customer_relationship"], "old_customer")
        self.assertEqual(sources["budget_level"], "manual")
        self.assertEqual(sources["service_team_size"], "ai")
        self.assertEqual(sources["customer_relationship"], "manual")
        self.assertEqual(sources["poc_result"], "none")


class CardEvaluateRequestValidationTests(unittest.TestCase):
    def test_manual_mode_requires_manual_dimensions(self):
        with self.assertRaises(ValidationError):
            CardEvaluateRequest(card_type="A", analysis_mode="manual")

    def test_hybrid_mode_requires_text_when_ai_dimensions_missing(self):
        with self.assertRaises(ValidationError):
            CardEvaluateRequest(
                card_type="B",
                analysis_mode="hybrid",
                manual_dimensions={"customer_relationship": "old_customer"},
            )


class CardEvaluationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_mode_skips_ai_and_scores_b_card_dimensions(self):
        payload = CardEvaluateRequest(
            card_type="B",
            analysis_mode="manual",
            manual_dimensions={
                "customer_relationship": "old_customer",
                "poc_result": "success",
            },
        )

        with patch("app.api.routes.card_evaluations.extract_scoring_dimensions_from_text", new=AsyncMock()) as mocked:
            result = await evaluate_card_view(payload)

        self.assertEqual(result.raw_score, 25)
        self.assertEqual(result.normalized_score, 25)
        self.assertEqual(result.merged_dimensions["customer_relationship"], "old_customer")
        detail_by_key = {item.key: item for item in result.dimensions}
        self.assertEqual(detail_by_key["customer_relationship"].source, "manual")
        self.assertEqual(detail_by_key["poc_result"].source, "manual")
        mocked.assert_not_awaited()

    async def test_ai_mode_reuses_cached_ai_dimensions_for_b_card(self):
        payload = CardEvaluateRequest(
            card_type="B",
            analysis_mode="ai",
            text="cached text",
            ai_dimensions={"customer_relationship": "old_customer"},
        )

        with patch("app.api.routes.card_evaluations.extract_scoring_dimensions_from_text", new=AsyncMock()) as mocked:
            result = await evaluate_card_view(payload)

        self.assertEqual(result.ai_dimensions["customer_relationship"], "old_customer")
        self.assertEqual(result.merged_dimensions["customer_relationship"], "old_customer")
        mocked.assert_not_awaited()

    async def test_hybrid_mode_merges_manual_and_ai_dimensions_for_b_card(self):
        payload = CardEvaluateRequest(
            card_type="B",
            analysis_mode="hybrid",
            text="fresh text",
            manual_dimensions={
                "budget_level": "low",
                "customer_relationship": "new_customer_middle_or_above",
            },
        )

        with patch(
            "app.api.routes.card_evaluations.extract_scoring_dimensions_from_text",
            new=AsyncMock(
                return_value={
                    "budget_level": "enough",
                    "deal_cycle": "short",
                    "poc_result": "partial_success",
                }
            ),
        ) as mocked:
            result = await evaluate_card_view(payload)

        self.assertEqual(result.merged_dimensions["budget_level"], "low")
        self.assertEqual(result.merged_dimensions["deal_cycle"], "short")
        detail_by_key = {item.key: item for item in result.dimensions}
        self.assertEqual(detail_by_key["budget_level"].source, "manual")
        self.assertEqual(detail_by_key["deal_cycle"].source, "ai")
        mocked.assert_awaited_once()

    async def test_invalid_b_card_manual_fields_return_400(self):
        payload = CardEvaluateRequest(
            card_type="B",
            analysis_mode="manual",
            manual_dimensions={
                "customer_relationship": "old_customer",
                "budget": "above_3_million",
            },
        )

        with self.assertRaises(HTTPException) as ctx:
            await evaluate_card_view(payload)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Invalid scoring fields", ctx.exception.detail)

    async def test_ai_extraction_failure_returns_502(self):
        payload = CardEvaluateRequest(
            card_type="B",
            analysis_mode="ai",
            text="need extraction",
        )

        with patch(
            "app.api.routes.card_evaluations.extract_scoring_dimensions_from_text",
            new=AsyncMock(side_effect=RuntimeError("invalid enum")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await evaluate_card_view(payload)

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.detail, "invalid enum")


if __name__ == "__main__":
    unittest.main()
