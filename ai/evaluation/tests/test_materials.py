"""Material conversion behavior through actual CLI processes; no model measurements."""
from __future__ import annotations

import argparse
import gettext
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from scripts.materials_smoke import CommandEnvironment, copy_materials, replace_file, run_cli
from zoop_eval.materials import DEFAULT_MATERIALS


class CommandEnvironmentTest(unittest.TestCase):
    def test_argparse_observations_are_separate_from_application_reads(self):
        effects, observations = {"environmentReads": 0}, {}
        with patch.object(os, "environ", CommandEnvironment(effects, observations)):
            parser = argparse.ArgumentParser(prog="material-guard-test")
            parser.add_argument("--dataset")
            parser.parse_args([])
        self.assertEqual(effects["environmentReads"], 0)
        self.assertTrue(observations)
        self.assertTrue(any(key == "COLUMNS" for key, _ in observations))
        self.assertTrue(any(key == "LANGUAGE" for key, _ in observations))
        if hasattr(argparse.HelpFormatter, "_set_color"):
            self.assertTrue(any(key == "PYTHON_COLORS" for key, _ in observations))

    def test_application_display_and_credential_probes_are_denied(self):
        keys = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG", "COLUMNS", "LINES",
                "PYTHON_COLORS", "NO_COLOR", "FORCE_COLOR", "TERM", "TYPESAFE_API_KEY")
        for key in keys:
            with self.subTest(key=key):
                effects, observations = {"environmentReads": 0}, {}
                with patch.object(os, "environ", CommandEnvironment(effects, observations)):
                    with self.assertRaises(AssertionError):
                        os.environ.get(key)
                self.assertEqual(effects["environmentReads"], 1)
                self.assertEqual(observations, {})

    def test_stdlib_helpers_without_argparse_cannot_hide_application_reads(self):
        for lookup in (lambda: shutil.get_terminal_size(), lambda: gettext.find("material-guard-test")):
            effects, observations = {"environmentReads": 0}, {}
            with patch.object(os, "environ", CommandEnvironment(effects, observations)):
                with self.assertRaises(AssertionError):
                    lookup()
            self.assertEqual(effects["environmentReads"], 1)
            self.assertEqual(observations, {})
        # _safe_getenv catches Exception internally. The counter must still catch
        # a disallowed caller even when the stdlib helper swallows the exception.
        colorize = sys.modules.get("_colorize")
        if colorize is not None:
            effects, observations = {"environmentReads": 0}, {}
            with patch.object(os, "environ", CommandEnvironment(effects, observations)):
                colorize.can_colorize()
            self.assertGreater(effects["environmentReads"], 0)
            self.assertEqual(observations, {})


class MaterialsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zoop-material-test-")
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name)
        copy_materials(self.target)

    def document(self, name):
        return json.loads((self.target / name).read_text("utf-8"))

    def manifest(self, mutate):
        doc = self.document("manifest.json")
        mutate(doc)
        (self.target / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")

    def invoke(self, command="materials-validate", dataset=None, *, code=0, target=None):
        args = [command, "--materials", str(target or self.target)]
        if dataset:
            args.extend(("--dataset", dataset))
        result = run_cli(*args)
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        doc = json.loads(result.stdout, parse_float=Decimal)
        self.assertIs(doc["ok"], code == 0)
        audit = json.loads(result.stderr)
        self.assertFalse(any(audit["audit"].values()), audit)
        if code == 2:
            self.assertEqual(set(doc), {"ok", "error"})
            self.assertEqual(set(doc["error"]), {"code", "message"})
            self.assertNotIn(str(self.target), result.stdout)
        return doc, result, audit

    def reject_mutation(self, name, mutate, command="materials-validate", dataset=None):
        doc = self.document(name)
        mutate(doc)
        replace_file(self.target, name, doc)
        return self.invoke(command, dataset, code=2)[0]["error"]["code"]

    def test_real_counts_attribution_and_distinct_validation_scope(self):
        validation, _, _ = self.invoke(target=DEFAULT_MATERIALS)
        self.assertEqual(validation["schema"], "zoop-eval-material-validation-1")
        self.assertEqual(validation["counts"], {"klue-re": {"records": 20, "entitySpansChecked": 40},
                                                "tatqa": {"contexts": 5, "questions": 30}})
        self.assertEqual(validation["status"], "development-intake")
        self.assertEqual(validation["validationScope"], "manifest-and-all-inputs-and-gold")
        sources = validation["provenance"]["sources"]
        self.assertEqual([s["license"] for s in sources], ["CC-BY-SA-4.0", "CC-BY-4.0"])
        self.assertFalse(sources[0]["revisionBindingVerified"])
        self.assertEqual(sources[1]["creators"][0], "Fengbin Zhu")
        self.assertEqual(len(validation["provenance"]["verifiedFiles"]), 4)
        inputs, _, _ = self.invoke("materials-inputs", "klue-re")
        self.assertEqual(inputs["validationScope"], "manifest-and-selected-input-only")
        self.assertEqual(len(inputs["provenance"]["verifiedFiles"]), 1)
        self.assertEqual(len(inputs["choices"]), 30)
        self.assertEqual(inputs["choices"][5], "org:member_of")
        self.assertEqual(inputs["choices"][29], "per:title")
        gold, _, _ = self.invoke("materials-gold", "klue-re")
        self.assertEqual(gold["cases"][2], {"guid": "klue-re-v1_train_00002", "labelId": 5, "label": "org:member_of"})

    def test_input_only_never_opens_gold_unreadable_absent_or_old_default(self):
        for dataset in ("klue-re", "tatqa"):
            with self.subTest(dataset=dataset):
                copy_materials(self.target)
                for name in ("klue-re.gold.json", "tatqa.gold.json"):
                    (self.target / name).chmod(0)
                try:
                    _, _, audit = self.invoke("materials-inputs", dataset)
                    self.assertEqual(audit["opened"], [str(self.target), "manifest.json", f"{dataset}.inputs.json"])
                finally:
                    for name in ("klue-re.gold.json", "tatqa.gold.json"):
                        (self.target / name).chmod(0o600)
                        (self.target / name).unlink()
                other = "tatqa" if dataset == "klue-re" else "klue-re"
                (self.target / f"{other}.inputs.json").unlink()
                _, _, audit = self.invoke("materials-inputs", dataset)
                self.assertEqual(audit["opened"], [str(self.target), "manifest.json", f"{dataset}.inputs.json"])
                self.invoke("materials-gold", dataset, code=2)

    def test_gold_independent_public_choices_and_no_annotation_leak(self):
        before, raw, _ = self.invoke("materials-inputs", "klue-re")
        (self.target / "klue-re.gold.json").write_text("not JSON or a label list", encoding="utf-8")
        after, raw_after, _ = self.invoke("materials-inputs", "klue-re")
        self.assertEqual(before, after)
        self.assertEqual(raw.stdout, raw_after.stdout)
        self.invoke("materials-gold", "klue-re", code=2)
        doc, _, _ = self.invoke("materials-inputs", "tatqa")
        forbidden = {"answer", "answer_type", "answer_from", "derivation", "scale", "rel_paragraphs", "req_comparison", "paragraphIds"}

        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(doc)
        self.assertEqual(doc["contexts"][0]["table"][4][1], "$1,496.5")
        self.assertIn("cost-plus", doc["contexts"][0]["paragraphs"][1]["text"])
        self.assertEqual(doc["cases"][0]["contextId"], doc["contexts"][0]["tableUid"])

    def test_unicode_astral_half_open_span_preserves_exact_text(self):
        doc = self.document("klue-re.inputs.json")
        row = doc["records"][0]
        row.update(sentence="가\U0001f600나", subject_entity={"word": "\U0001f600", "start_idx": 1, "end_idx": 1, "type": "POH"},
                   object_entity={"word": "나", "start_idx": 2, "end_idx": 2, "type": "PER"})
        replace_file(self.target, "klue-re.inputs.json", doc)
        inputs, _, _ = self.invoke("materials-inputs", "klue-re")
        case = inputs["cases"][0]
        self.assertEqual(case["sentence"], "가\U0001f600나")
        self.assertEqual(case["subjectEntity"], {"text": "\U0001f600", "type": "POH",
                         "span": {"start": 1, "end": 2, "unit": "unicode-codepoint", "endExclusive": True}})
        self.assertEqual(case["objectEntity"]["span"]["end"], 3)
        for bad in (True, "1", 1.0, -1, 9):
            with self.subTest(bad=bad):
                changed = copy.deepcopy(doc)
                changed["records"][0]["subject_entity"]["start_idx"] = bad
                replace_file(self.target, "klue-re.inputs.json", changed)
                self.invoke("materials-inputs", "klue-re", code=2)
        row["subject_entity"]["word"] = "different"
        replace_file(self.target, "klue-re.inputs.json", doc)
        self.invoke("materials-inputs", "klue-re", code=2)

    def test_tatqa_paragraph_mapping_and_original_units(self):
        gold, _, _ = self.invoke("materials-gold", "tatqa")
        self.assertEqual(gold["cases"][0]["rel_paragraphs"], ["2"])
        self.assertEqual(gold["cases"][0]["paragraphIds"], ["79e37805-6558-4a8c-b033-32be6bffef48"])
        self.assertEqual(gold["cases"][19]["paragraphIds"], ["f29913b5-4c58-4c6c-bc56-f32743aa3eab"])
        self.assertEqual(gold["cases"][4]["answer"], Decimal("-12.6"))
        self.assertEqual(gold["cases"][4]["scale"], "million")
        self.assertEqual(gold["cases"][5]["answer"], Decimal("-22.22"))
        self.assertEqual(gold["cases"][5]["scale"], "percent")
        self.assertEqual(gold["cases"][24]["scale"], "thousand")
        self.assertEqual(gold["cases"][18]["answer"][-1], "")
        self.assertEqual(gold["cases"][9]["paragraphIds"], [])
        self.assertEqual(gold["cases"][9]["derivation"], "918>914>814")
        inputs, _, _ = self.invoke("materials-inputs", "tatqa")
        self.assertEqual(inputs["contexts"][3]["table"][1][1], "2019 €m")
        self.assertEqual(inputs["contexts"][4]["table"][2][1], "U.S. $ in thousands")
        self.assertNotIn("tableCells", gold["cases"][9])

    def test_precision_and_unknown_annotations_are_not_inferred(self):
        raw = (self.target / "tatqa.gold.json").read_bytes().replace(b'"answer": -12.6,', b'"answer": -12.600000000000000000000000000001,', 1)
        replace_file(self.target, "tatqa.gold.json", raw=raw)
        gold, result, _ = self.invoke("materials-gold", "tatqa")
        self.assertEqual(gold["cases"][4]["answer"], Decimal("-12.600000000000000000000000000001"))
        self.assertIn("-12.600000000000000000000000000001", result.stdout)
        doc = self.document("tatqa.gold.json")
        question = doc["records"][0]["questions"][0]
        question.update(answer=None, answer_type="unknown-upstream-kind", answer_from=None,
                        scale="", derivation=None, rel_paragraphs=None, req_comparison=None)
        replace_file(self.target, "tatqa.gold.json", doc)
        gold, _, _ = self.invoke("materials-gold", "tatqa")
        self.assertIsNone(gold["cases"][0]["answer"])
        self.assertIsNone(gold["cases"][0]["paragraphIds"])
        self.assertEqual(gold["cases"][0]["answer_type"], "unknown-upstream-kind")
        self.assertEqual(gold["cases"][0]["scale"], "")

    def test_out_of_range_exponents_are_sanitized_for_gold_and_validation(self):
        original = (self.target / "tatqa.gold.json").read_bytes()
        for token in (b"1e9999999999999999999", b"1e-9999999999999999999"):
            raw = original.replace(b'"answer": -12.6,', b'"answer": ' + token + b',', 1)
            replace_file(self.target, "tatqa.gold.json", raw=raw)
            for command, dataset in (("materials-gold", "tatqa"), ("materials-validate", None)):
                with self.subTest(token=token, command=command):
                    rejected, result, _ = self.invoke(command, dataset, code=2)
                    self.assertEqual(rejected["error"]["code"], "materials_invalid")
                    self.assertNotIn(token.decode(), result.stdout)
                    self.assertNotIn("Traceback", result.stderr)

    def test_representable_large_exponent_stays_exact_and_compact(self):
        raw = (self.target / "tatqa.gold.json").read_bytes().replace(
            b'"answer": -12.6,', b'"answer": 1e100000,', 1)
        replace_file(self.target, "tatqa.gold.json", raw=raw)
        gold, result, _ = self.invoke("materials-gold", "tatqa")
        self.assertEqual(gold["cases"][4]["answer"], Decimal("1e100000"))
        self.assertIn('"answer":1E+100000', result.stdout)

    def test_canonical_bytes_bind_exact_inputs_and_are_deterministic(self):
        for dataset in ("klue-re", "tatqa"):
            with self.subTest(dataset=dataset):
                _, first, _ = self.invoke("materials-inputs", dataset)
                _, second, _ = self.invoke("materials-inputs", dataset)
                self.assertEqual(first.stdout, second.stdout)
                gold, first_gold, _ = self.invoke("materials-gold", dataset)
                _, second_gold, _ = self.invoke("materials-gold", dataset)
                self.assertEqual(first_gold.stdout, second_gold.stdout)
                expected = hashlib.sha256(first.stdout.removesuffix("\n").encode("utf-8")).hexdigest()
                self.assertEqual(gold["inputsSha256"], expected)
                validation, _, _ = self.invoke()
                self.assertEqual(validation["inputsSha256"][dataset], expected)
        old, _, _ = self.invoke("materials-gold", "klue-re")
        doc = self.document("klue-re.inputs.json")
        doc["records"][0]["source"] = "synthetic-source-change"
        replace_file(self.target, "klue-re.inputs.json", doc)
        changed, _, _ = self.invoke("materials-gold", "klue-re")
        self.assertNotEqual(changed["inputsSha256"], old["inputsSha256"])

    def test_hash_and_size_fail_closed_without_partial_success(self):
        path = self.target / "tatqa.gold.json"
        raw = path.read_bytes()
        path.write_bytes(raw + b" ")
        doc, _, _ = self.invoke(code=2)
        self.assertEqual(doc["error"]["code"], "materials_size_mismatch")
        path.write_bytes(raw.replace(b'"span"', b'"spam"', 1))
        doc, _, _ = self.invoke(code=2)
        self.assertEqual(doc["error"]["code"], "materials_hash_mismatch")

    def test_manifest_paths_roles_and_types(self):
        original = self.document("manifest.json")
        for path in ("../.env", "/tmp/.env", ".env", "nested/klue-re.inputs.json", "tatqa.gold.json"):
            with self.subTest(path=path):
                doc = copy.deepcopy(original)
                doc["files"][0]["path"] = path
                (self.target / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
                self.invoke("materials-inputs", "klue-re", code=2)
        for key, value in (("role", "gold"), ("bytes", True), ("bytes", 1.0), ("sha256", "bad")):
            with self.subTest(key=key, value=value):
                doc = copy.deepcopy(original)
                doc["files"][0][key] = value
                (self.target / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
                self.invoke(code=2)
        doc = copy.deepcopy(original)
        doc["files"].append(doc["files"][0])
        (self.target / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
        self.invoke(code=2)

    def test_nonregular_and_symlink_files_never_followed(self):
        name = self.target / "klue-re.inputs.json"
        name.unlink()
        name.symlink_to(self.target / "klue-re.gold.json")
        self.invoke("materials-inputs", "klue-re", code=2)
        name.unlink()
        os.mkfifo(name)
        self.invoke("materials-inputs", "klue-re", code=2)
        name.unlink()
        copy_materials(self.target)
        path = self.target / "manifest.json"
        path.unlink()
        path.symlink_to(self.target / "klue-re.gold.json")
        self.invoke("materials-inputs", "klue-re", code=2)

    def test_duplicate_orphan_and_missing_source_identities(self):
        changes = [
            ("klue-re.inputs.json", lambda d: d["records"].append(d["records"][0])),
            ("klue-re.gold.json", lambda d: d["records"][0].update(guid="orphan")),
            ("klue-re.gold.json", lambda d: d["records"].pop()),
            ("klue-re.gold.json", lambda d: d["records"].append(d["records"][0])),
            ("tatqa.inputs.json", lambda d: d["records"][1]["table"].update(uid=d["records"][0]["table"]["uid"])),
            ("tatqa.inputs.json", lambda d: d["records"][0]["paragraphs"].append(d["records"][0]["paragraphs"][0])),
            ("tatqa.inputs.json", lambda d: d["records"][1]["questions"][0].update(uid=d["records"][0]["questions"][0]["uid"])),
            ("tatqa.inputs.json", lambda d: d["records"][0]["questions"][1].update(order=1)),
            ("tatqa.gold.json", lambda d: d["records"][0].update(tableUid="orphan")),
            ("tatqa.gold.json", lambda d: d["records"][0]["questions"][0].update(uid="orphan")),
            ("tatqa.gold.json", lambda d: d["records"][0]["questions"].append(d["records"][0]["questions"][0])),
            ("tatqa.gold.json", lambda d: d["records"][0]["questions"].pop()),
            ("tatqa.gold.json", lambda d: d["records"][0]["questions"][0].update(uid=d["records"][1]["questions"][0]["uid"])),
        ]
        for name, mutate in changes:
            with self.subTest(name=name, mutation=changes.index((name, mutate))):
                copy_materials(self.target)
                self.reject_mutation(name, mutate)

    def test_forged_klue_labels_are_rejected(self):
        for value in (True, 0.0, "0", -1, 30):
            with self.subTest(value=value):
                copy_materials(self.target)
                self.reject_mutation("klue-re.gold.json", lambda d: d["records"][0].update(label=value))
        copy_materials(self.target)
        self.reject_mutation("klue-re.gold.json", lambda d: d["records"][0].update(labelName="org:members"))
        copy_materials(self.target)
        self.reject_mutation("klue-re.gold.json", lambda d: d["labels"].reverse())

    def test_tatqa_support_and_annotation_types_are_strict(self):
        for key, value in (("rel_paragraphs", ["999"]), ("rel_paragraphs", [2]), ("rel_paragraphs", [True]),
                           ("rel_paragraphs", ["2", "2"]), ("answer", True), ("answer", {"value": 1}),
                           ("answer", [1]), ("answer_type", 1), ("scale", False), ("req_comparison", 0)):
            with self.subTest(key=key, value=value):
                copy_materials(self.target)
                self.reject_mutation("tatqa.gold.json", lambda d: d["records"][0]["questions"][0].update({key: value}))
        copy_materials(self.target)
        self.reject_mutation("tatqa.inputs.json", lambda d: d["records"][0]["paragraphs"][0].update(order=True))

    def test_extra_annotation_keys_rejected_at_each_input_boundary(self):
        for key in ("answer", "answer_type", "answer_from", "derivation", "scale", "rel_paragraphs", "req_comparison", "support"):
            with self.subTest(key=key):
                copy_materials(self.target)
                self.reject_mutation("tatqa.inputs.json", lambda d: d["records"][0]["questions"][0].update({key: "private-canary"}),
                                     "materials-inputs", "tatqa")
        for name, mutate in (
            ("klue-re.inputs.json", lambda d: d["records"][0].update(label=0)),
            ("tatqa.inputs.json", lambda d: d["records"][0]["table"].update(answer="private-canary")),
            ("tatqa.inputs.json", lambda d: d["records"][0]["paragraphs"][0].update(support=True)),
            ("tatqa.gold.json", lambda d: d["records"][0]["questions"][0].update(table_cells=[[1, 2]])),
        ):
            copy_materials(self.target)
            self.reject_mutation(name, mutate)

    def test_strict_json_and_sanitized_errors(self):
        original = (self.target / "klue-re.inputs.json").read_bytes()
        for raw in (b'{"private-canary":1,"private-canary":2}', b'{"value":NaN}', b'{"value":Infinity}',
                    b'{"value":-Infinity}', b'\xff', b'{"value":"\\ud800"}', b'[' * 1200 + b']' * 1200):
            with self.subTest(raw=raw[:40]):
                replace_file(self.target, "klue-re.inputs.json", raw=raw)
                _, result, _ = self.invoke("materials-inputs", "klue-re", code=2)
                self.assertNotIn("private-canary", result.stdout)
                self.assertNotIn("Traceback", result.stdout)
        replace_file(self.target, "klue-re.inputs.json", raw=original)
        self.manifest(lambda d: d["sources"][0]["counts"].update(records=True))
        self.invoke(code=2)

    def test_file_byte_cap_and_argument_rejection(self):
        self.manifest(lambda d: d["files"][0].update(bytes=8 * 1024 * 1024 + 1))
        doc, _, _ = self.invoke("materials-inputs", "klue-re", code=2)
        self.assertEqual(doc["error"]["code"], "materials_file_size")
        copy_materials(self.target)
        with (self.target / "klue-re.inputs.json").open("r+b") as handle:
            handle.truncate(8 * 1024 * 1024 + 1)
        doc, _, _ = self.invoke("materials-inputs", "klue-re", code=2)
        self.assertEqual(doc["error"]["code"], "materials_file_size")
        for args in (("materials-inputs",), ("materials-inputs", "--dataset", "private-canary"),
                     ("materials-validate", "--out", "/private-canary"),
                     ("materials-validate", "--dataset", "tatqa")):
            with self.subTest(args=args):
                result = run_cli(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                doc = json.loads(result.stdout)
                self.assertEqual(doc["error"]["code"], "materials_arguments")
                self.assertNotIn("private-canary", result.stdout)
                self.assertEqual(json.loads(result.stderr)["opened"], [])

    def test_input_gold_shapes_cannot_be_swapped_or_scored(self):
        gold = self.document("klue-re.gold.json")
        replace_file(self.target, "klue-re.inputs.json", gold)
        self.invoke("materials-inputs", "klue-re", code=2)
        copy_materials(self.target)
        inputs = self.document("tatqa.inputs.json")
        replace_file(self.target, "tatqa.gold.json", inputs)
        self.invoke("materials-gold", "tatqa", code=2)
        copy_materials(self.target)
        for command in ("materials-inputs", "materials-gold"):
            _, result, _ = self.invoke(command, "klue-re")
            artifact = self.target / "artifact.json"
            artifact.write_text(result.stdout, encoding="utf-8")
            scored = run_cli("score", str(artifact), audited=False)
            self.assertEqual(scored.returncode, 2, scored.stderr)
            rejected = json.loads(scored.stdout)
            self.assertFalse(rejected["ok"])
            self.assertEqual(set(rejected), {"ok", "error"})


if __name__ == "__main__":
    unittest.main()
