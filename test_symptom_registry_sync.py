"""
test_symptom_registry_sync.py — Sync tests for symptom_registry + symptom_class_registry
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from routers.services.symptom_registry import SYMPTOM_REGISTRY, normalize_symptom
from routers.services.symptom_class_registry import SYMPTOM_CLASS_MAP, get_symptom_class


# ═════════════════════════════════════════════════════════════════════════════
# Section 1 — normalize_symptom()
# ═════════════════════════════════════════════════════════════════════════════

class TestNormalizeSymptom(unittest.TestCase):

    # T1: Every symptom in SYMPTOM_REGISTRY normalizes to itself (not None)
    def test_all_registry_symptoms_normalize(self):
        for symptom in SYMPTOM_REGISTRY:
            with self.subTest(symptom=symptom):
                result = normalize_symptom(symptom)
                self.assertIsNotNone(result, f"normalize_symptom('{symptom}') returned None")
                self.assertEqual(result, symptom)

    # T2: Removed dead key — blood_in_vomit → None
    def test_blood_in_vomit_returns_none(self):
        self.assertIsNone(normalize_symptom("blood_in_vomit"))

    # T3: Removed dead key — blood_in_stool → None
    def test_blood_in_stool_returns_none(self):
        self.assertIsNone(normalize_symptom("blood_in_stool"))

    # T4: seizure is in registry
    def test_seizure_normalizes(self):
        self.assertEqual(normalize_symptom("seizure"), "seizure")

    # T5: None input → None
    def test_none_input_returns_none(self):
        self.assertIsNone(normalize_symptom(None))

    # T6: Unknown symptom → None
    def test_unknown_symptom_returns_none(self):
        self.assertIsNone(normalize_symptom("headache"))

    # T7: Case-insensitive (uppercase input)
    def test_uppercase_normalizes(self):
        self.assertEqual(normalize_symptom("VOMITING"), "vomiting")

    # T8: Whitespace trimmed
    def test_whitespace_trimmed(self):
        self.assertEqual(normalize_symptom("  diarrhea  "), "diarrhea")


# ═════════════════════════════════════════════════════════════════════════════
# Section 2 — get_symptom_class()
# ═════════════════════════════════════════════════════════════════════════════

class TestGetSymptomClass(unittest.TestCase):

    # T1: Every symptom in SYMPTOM_REGISTRY has an explicit entry in SYMPTOM_CLASS_MAP
    def test_all_registry_symptoms_have_explicit_class(self):
        for symptom in SYMPTOM_REGISTRY:
            with self.subTest(symptom=symptom):
                self.assertIn(
                    symptom,
                    SYMPTOM_CLASS_MAP,
                    f"'{symptom}' is in SYMPTOM_REGISTRY but missing from SYMPTOM_CLASS_MAP"
                )

    # T2: fever → "GENERAL" (explicit, not fallthrough)
    def test_fever_is_general(self):
        self.assertEqual(get_symptom_class("fever"), "GENERAL")

    # T3: eye_discharge → "OCULAR"
    def test_eye_discharge_is_ocular(self):
        self.assertEqual(get_symptom_class("eye_discharge"), "OCULAR")

    # T4: abdominal_pain → "GI"
    def test_abdominal_pain_is_gi(self):
        self.assertEqual(get_symptom_class("abdominal_pain"), "GI")

    # T5: regurgitation → "GI"
    def test_regurgitation_is_gi(self):
        self.assertEqual(get_symptom_class("regurgitation"), "GI")

    # T6: urinary_obstruction → "URINARY"
    def test_urinary_obstruction_is_urinary(self):
        self.assertEqual(get_symptom_class("urinary_obstruction"), "URINARY")

    # T7: No duplicate key for "seizure" — map has exactly one entry for it
    def test_seizure_no_duplicate(self):
        self.assertEqual(get_symptom_class("seizure"), "NEURO")
        # dict keys are unique by definition — verify the count via items
        neuro_seizure_count = sum(
            1 for k, v in SYMPTOM_CLASS_MAP.items() if k == "seizure"
        )
        self.assertEqual(neuro_seizure_count, 1)

    # T8: constipation → "GI"
    def test_constipation_is_gi(self):
        self.assertEqual(get_symptom_class("constipation"), "GI")

    # T9: loss_of_appetite → "GI"
    def test_loss_of_appetite_is_gi(self):
        self.assertEqual(get_symptom_class("loss_of_appetite"), "GI")

    # T10: weakness → "GENERAL"
    def test_weakness_is_general(self):
        self.assertEqual(get_symptom_class("weakness"), "GENERAL")

    # T11: lethargy → "GENERAL"
    def test_lethargy_is_general(self):
        self.assertEqual(get_symptom_class("lethargy"), "GENERAL")

    # T12: injury → "TRAUMA"
    def test_injury_is_trauma(self):
        self.assertEqual(get_symptom_class("injury"), "TRAUMA")

    # T13: None/empty → "UNKNOWN"
    def test_empty_returns_unknown(self):
        self.assertEqual(get_symptom_class(""), "UNKNOWN")
        self.assertEqual(get_symptom_class(None), "UNKNOWN")

    # T14: truly unknown symptom falls through to "GENERAL"
    def test_unknown_symptom_fallthrough(self):
        self.assertEqual(get_symptom_class("headache"), "GENERAL")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestNormalizeSymptom))
    suite.addTests(loader.loadTestsFromTestCase(TestGetSymptomClass))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-'*60}")
    print(f"TOTAL: {passed}/{total} PASS")
