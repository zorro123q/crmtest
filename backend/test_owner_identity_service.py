import unittest
from types import SimpleNamespace

from app.api.routes.leads import _can_edit_lead
from app.api.routes.opportunities import _can_edit_opportunity
from app.services.owner_identity_service import owner_name_matches_user, owner_username_candidates


class OwnerIdentityServiceTests(unittest.TestCase):
    def test_chinese_owner_name_maps_to_login_username(self):
        self.assertEqual(owner_username_candidates("王保三")[0], "bswang")
        self.assertEqual(owner_username_candidates("臧春梅")[0], "cmzang")
        self.assertEqual(owner_username_candidates("李鑫健")[0], "xjli")
        self.assertEqual(owner_username_candidates("余浩然")[0], "hryv")
        self.assertEqual(owner_username_candidates("杨序东")[0], "xdyang")
        self.assertEqual(owner_username_candidates("杨序冬")[0], "xdyang")
        self.assertEqual(owner_username_candidates("杨俊波")[0], "jbyang")

    def test_chen_qi_name_variant_maps_to_cq(self):
        self.assertEqual(owner_username_candidates("陈棋")[0], "cq")
        self.assertEqual(owner_username_candidates("陈祺")[0], "cq")

    def test_owner_name_matches_current_login_account(self):
        self.assertTrue(owner_name_matches_user(SimpleNamespace(username="bswang"), "王保三"))
        self.assertTrue(owner_name_matches_user(SimpleNamespace(username="cq"), "陈祺"))
        self.assertTrue(owner_name_matches_user(SimpleNamespace(username="xjli"), " xjli "))
        self.assertFalse(owner_name_matches_user(SimpleNamespace(username="cmzang"), "王保三"))

    def test_lead_edit_allows_business_owner_match_when_owner_id_is_stale(self):
        user = SimpleNamespace(id="real-user-id", username="xjli", is_admin=False)
        lead = SimpleNamespace(owner_id="stale-import-user-id", custom_fields={"business_owner": "李鑫健"})

        self.assertTrue(_can_edit_lead(user, lead))

    def test_opportunity_edit_allows_business_owner_match_when_owner_id_is_stale(self):
        user = SimpleNamespace(id="real-user-id", username="hryv", is_admin=False)
        opportunity = SimpleNamespace(
            owner_id="stale-import-user-id",
            custom_fields={"owner_name_display": "余浩然"},
        )

        self.assertTrue(_can_edit_opportunity(user, opportunity))


if __name__ == "__main__":
    unittest.main()
