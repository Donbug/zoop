"""The document generator must not silently promote historical or malformed detail IDs to the active index.

Skipped under the bare `make tooling-test` interpreter (no PyYAML/openpyxl); `make public-check` runs it in its bootstrapped env.
"""
from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_build():
    try:
        import openpyxl  # noqa: F401
        import yaml  # noqa: F401
    except ModuleNotFoundError:
        raise unittest.SkipTest("PyYAML/openpyxl are required to import the generator")
    spec = importlib.util.spec_from_file_location("zoop_doc_build", ROOT / "docs/system/build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def definition(file: str, row: int, heading_text: str | None = None, heading_row: int | None = None) -> dict:
    heading = {"row": heading_row or row - 2, "text": heading_text} if heading_text else None
    return {"source": {"path": f"raw/{file}", "row": row, "rowUnit": "xlsx-row"}, "fields": {}, "heading": heading, "meta": ""}


def spec(status: str, definitions: list, requirements: list | None = None) -> dict:
    return {"status": status, "requirementIds": requirements or [], "definitions": definitions}


CHART = {"1d": "5m", "1w": "1h"}


def operation(oid: str, fs: list, screens: list, requirements: list | None = None, status: dict | None = None, nfs: list | None = None) -> dict:
    x = {"fsIds": fs, "nfsIds": nfs or [], "screenIds": screens, "wbsIds": [], "requirementIds": requirements or []}
    if status:
        x["featureStatus"] = status
    return {"get": {"operationId": oid, "x-zoop": x}}


def fixture():
    specs = {
        "FS046": spec("팀 검토 전", [definition("07-old.csv", 23), definition("08-v2.csv", 23)], ["46"]),
        "FS050-01": spec("목차 없음", [definition("07-old.csv", 79)]),
        "FS066-01": spec("미기재", [definition("11-admin.csv", 23)], ["78"]),
        "ㅊ": spec("목차 없음", [definition("05-brief.csv", 134, "FS066-01  브리핑 리뷰", 132)]),
    }
    links = {
        "authority": {"chartResolution": CHART, "implementationScope": {"exceptions": []}},
        "detailAuthority": {
            "historicalSheets": [{"file": "07-old.csv", "supersededBy": "08-v2.csv", "specIds": ["FS046", "FS050-01"]}],
            "historicalOnlySpecIds": ["FS050-01"],
            "rawIdCorrections": [{"rawId": "ㅊ", "effectiveSpecId": "FS066-01", "file": "05-brief.csv", "headingRow": 132, "idRow": 134}],
            "legacyAiMeaning": [
                {"legacySpecId": "FS046", "legacySource": {"file": "07-old.csv", "row": 23}, "currentSpecIds": ["FS046", "FS066-01"],
                 "requirementIds": ["46"], "implementationJudgmentTo": []},
                {"legacySpecId": "FS050-01", "legacySource": {"file": "07-old.csv", "row": 79}, "currentSpecIds": ["FS066-01"],
                 "requirementIds": ["50"], "implementationJudgmentTo": []},
            ],
        },
    }
    links["authority"]["implementationScope"]["exceptions"] = [{
        "id": "EX", "specIds": ["FS046"], "requirementIds": ["46"], "userFacing": False, "retainedOperationIds": ["retained"]}]
    links["reservedRequirements"] = [{"requirementId": "78", "rawIndexSpecId": "FS066-01", "operationIds": ["fin"], "relatedRequirementIds": []}]
    series = {"interval": {"enum": list(CHART.values())}, "period": {"enum": list(CHART)}}
    status = {"state": "excluded-user-facing-endpoint-retained", "exceptionRef": "EX"}
    paths = {
        "/ordinary": operation("ordinary", fs=["FS046"], screens=["S1"]),
        "/retained": operation("retained", fs=["FS046"], screens=[], status=status),
        "/fin": operation("fin", fs=[], screens=["S1"], requirements=["78"]),
    }
    api = {"paths": paths, "x-zoop-approvals": {"chartResolution": CHART}, "components": {"schemas": {"PriceSeries": {"properties": series}}}}
    return specs, links, api


class DetailAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = load_build()

    def run_check(self, specs, links, api):
        findings: list[tuple] = []
        context = self.build.detail_authority(specs, links, api, {"46": [], "50": [], "78": []}, lambda *a: findings.append(a))
        return context, findings

    def test_valid_mapping_keeps_historical_and_malformed_ids_out_of_the_active_set(self):
        context, findings = self.run_check(*fixture())
        self.assertEqual(findings, [])
        self.assertEqual(context["active"], {"FS046", "FS066-01"})

    def test_unlisted_detail_only_id_is_a_hard_error_not_an_active_id(self):
        specs, links, api = fixture()
        links["detailAuthority"]["historicalOnlySpecIds"] = []
        _, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[0] == "DETAIL_AUTHORITY_INVALID" and f[1] == "FS050-01" and f[3] == "error" for f in findings))

    def test_historical_only_declaration_for_an_indexed_id_is_rejected(self):
        specs, links, api = fixture()
        links["detailAuthority"]["historicalOnlySpecIds"].append("FS046")
        _, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[1] == "FS046" for f in findings))

    def test_raw_id_correction_requires_the_current_heading_row(self):
        specs, links, api = fixture()
        specs = copy.deepcopy(specs)
        specs["ㅊ"]["definitions"][0]["heading"]["text"] = "FS036  브리핑 리뷰"
        _, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[1] == "ㅊ" for f in findings))

    def op(self, api, oid):
        return next(item["get"]["x-zoop"] for item in api["paths"].values() if item["get"]["operationId"] == oid)

    def test_declared_exceptions_allow_only_their_own_operations(self):
        context, findings = self.run_check(*fixture())
        self.assertEqual(findings, [])
        self.assertEqual(context["screenlessAllowed"], {"retained"})

    def test_ordinary_operation_without_function_ids_is_a_hard_error(self):
        specs, links, api = fixture()
        self.op(api, "ordinary")["fsIds"] = []
        _, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[0] == "API_WITHOUT_FUNCTION" and f[1] == "ordinary" and f[3] == "error" for f in findings))

    def test_common_nfs_ids_do_not_substitute_for_a_functional_spec(self):
        specs, links, api = fixture()
        ordinary = self.op(api, "ordinary")
        ordinary["fsIds"], ordinary["nfsIds"] = [], ["NFS001"]
        _, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[0] == "API_WITHOUT_FUNCTION" and f[1] == "ordinary" and f[3] == "error" for f in findings))

    def test_excluded_feature_operation_must_not_regain_an_active_screen(self):
        specs, links, api = fixture()
        self.op(api, "retained")["screenIds"] = ["S1"]
        context, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[0] == "EXCLUDED_FEATURE_HAS_SCREEN" and f[1] == "retained" and f[3] == "error" for f in findings))

    def test_reserved_operation_needs_a_valid_requirement_binding(self):
        specs, links, api = fixture()
        self.op(api, "fin")["requirementIds"] = []
        _, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[0] == "API_WITHOUT_FUNCTION" and f[1] == "fin" for f in findings))

    def test_arbitrary_excluded_status_cannot_waive_the_screen(self):
        specs, links, api = fixture()
        ordinary = self.op(api, "ordinary")
        ordinary["screenIds"] = []
        ordinary["featureStatus"] = {"state": "excluded-unapproved"}
        context, findings = self.run_check(specs, links, api)
        self.assertNotIn("ordinary", context["screenlessAllowed"])
        self.assertTrue(any(f[0] == "DETAIL_AUTHORITY_INVALID" and f[1] == "ordinary" for f in findings))

    def test_known_exception_ref_cannot_be_borrowed_by_another_operation(self):
        specs, links, api = fixture()
        ordinary = self.op(api, "ordinary")
        ordinary["screenIds"] = []
        ordinary["featureStatus"] = {"state": "excluded-user-facing-endpoint-retained", "exceptionRef": "EX"}
        context, findings = self.run_check(specs, links, api)
        self.assertNotIn("ordinary", context["screenlessAllowed"])
        self.assertTrue(any(f[1] == "ordinary" for f in findings))

    def test_retained_operation_loses_the_waiver_without_its_exception_status(self):
        specs, links, api = fixture()
        del self.op(api, "retained")["featureStatus"]
        context, findings = self.run_check(specs, links, api)
        self.assertNotIn("retained", context["screenlessAllowed"])
        self.assertTrue(any(f[1] == "EX" for f in findings))

    def test_historical_definition_follows_its_declared_migration_not_the_current_id_binding(self):
        specs, links, api = fixture()
        context, findings = self.run_check(specs, links, api)
        self.assertEqual(findings, [])
        bindings = {"FS046": {"effectiveRequirementIds": ["47"]}}
        old, new = specs["FS046"]["definitions"]
        self.assertEqual(self.build.effective_mapping("FS046", specs["FS046"], old, context, bindings), (["FS046", "FS066-01"], ["46"]))
        self.assertEqual(self.build.effective_mapping("FS046", specs["FS046"], new, context, bindings), (["FS046"], ["47"]))
        self.assertEqual(self.build.spec_mapping("FS050-01", specs["FS050-01"], context, bindings), (["FS066-01"], ["50"]))
        malformed = specs["ㅊ"]
        self.assertEqual(self.build.effective_mapping("ㅊ", malformed, malformed["definitions"][0], context, bindings), (["FS066-01"], []))

    def test_historical_definition_without_a_migration_entry_is_a_hard_error(self):
        specs, links, api = fixture()
        links["detailAuthority"]["legacyAiMeaning"] = links["detailAuthority"]["legacyAiMeaning"][:1]
        _, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[1] == "FS050-01" and f[3] == "error" for f in findings))

    def test_chart_resolution_must_match_the_contract_enum(self):
        specs, links, api = fixture()
        api["components"]["schemas"]["PriceSeries"]["properties"]["interval"]["enum"] = ["5m", "1d"]
        _, findings = self.run_check(specs, links, api)
        self.assertTrue(any(f[1] == "chartResolution" for f in findings))


class GeneratedProjectionTests(unittest.TestCase):
    """The committed outputs (kept drift-free by `repo_checks docs`) must project each historical definition separately."""

    @classmethod
    def setUpClass(cls):
        import json
        out = ROOT / "docs/system/out"
        if not (out / "acceptance-matrix.json").is_file():
            raise unittest.SkipTest("generated outputs are absent")
        cls.records = json.loads((out / "acceptance-matrix.json").read_text())["records"]
        cls.authority = json.loads((out / "effective-authority.json").read_text())["specs"]

    def row(self, spec_id, file, number):
        found = [r for r in self.records if r["specId"] == spec_id and r["definitionSource"]["path"].endswith(file)
                 and r["definitionSource"]["row"] == number]
        self.assertEqual(len(found), 1, (spec_id, file, number))
        return found[0]

    def check(self, row, state, ids, requirements):
        self.assertEqual((row["detailAuthority"], row["effectiveSpecIds"], row["effectiveRequirementIds"]), (state, ids, requirements))
        self.assertEqual(row["currentRuntimeVerification"], "미실행")

    def test_old_ai_rows_follow_legacy_meaning_while_current_rows_keep_the_current_binding(self):
        self.check(self.row("FS046", "07-AI-챗봇.csv", 23), "historical", ["FS045", "FS047", "FS051", "NFS001", "NFS003", "FS060"], ["46"])
        self.check(self.row("FS046", "08-AI-챗봇-v2.csv", 23), "current", ["FS046"], ["47"])
        self.check(self.row("FS051", "07-AI-챗봇.csv", 107), "historical", ["FS050"], ["51"])
        self.check(self.row("FS051", "08-AI-챗봇-v2.csv", 94), "current", ["FS051"], ["52", "53"])
        old = self.row("FS050-01", "07-AI-챗봇.csv", 79)
        self.check(old, "historical", ["FS049"], ["50"])
        self.assertEqual(old["specId"], "FS050-01")  # the raw historical ID stays visible
        self.assertEqual(self.authority["FS050-01"]["effectiveSpecIds"], ["FS049"])

    def test_malformed_briefing_id_projects_to_fs066_01_only(self):
        row = self.row("ㅊ", "05-출퇴근-브리핑.csv", 134)
        self.assertEqual(row["effectiveSpecIds"], ["FS066-01"])
        self.assertEqual(row["specId"], "ㅊ")


if __name__ == "__main__":
    unittest.main()
