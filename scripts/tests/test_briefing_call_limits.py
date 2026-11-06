import unittest
import briefing_call_limits as limits


class CallLimitsTests(unittest.TestCase):
    def test_legacy_caps_do_not_change_without_explicit_configuration(self):
        self.assertEqual(16,limits.environment_limit({}))
        limits.validate_auto({'nativeCallLimit':6})
        limits.validate_auto({'sharePriorityAnalysis':True,'nativeCallLimit':8})

    def test_native_and_publication_allotments_fit_one_shared_cap(self):
        cfg={'roundCallLimit':32,'sharePriorityAnalysis':True,'nativeCallLimit':24}
        limits.validate_auto(cfg)
        self.assertEqual(32,limits.native_limit(cfg)+limits.publication_reserve(cfg))
        for value in [25,True,0]:
            with self.assertRaises(ValueError):limits.validate_auto({**cfg,'nativeCallLimit':value})

    def test_environment_is_bounded_and_not_a_money_limit_override(self):
        self.assertEqual(32,limits.environment_limit({'BRIEFING_ROUND_CALL_LIMIT':'32'}))
        for value in ['-1','15','65','32.0',' 32','٣٢']:
            with self.assertRaises(ValueError):limits.environment_limit({'BRIEFING_ROUND_CALL_LIMIT':value})
