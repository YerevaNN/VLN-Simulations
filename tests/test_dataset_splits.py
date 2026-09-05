import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))
from dataset_splits import assign_split, load_registry, registry_digest, validate_assignments

class DatasetSplitTests(unittest.TestCase):
    def test_existing_variants_share_single_training_family(self):
        root = assign_split("natural-valley")
        for family in ("natural-valley-v1", "natural-valley-v2", "mountain-valley-v2"):
            self.assertEqual(root, assign_split(family))
        self.assertEqual(root["split"], "train")

    def test_new_family_assignment_stable_independent_of_execution_order(self):
        families = [f"independent-family-{i}" for i in range(100)]
        forward = {family: assign_split(family) for family in families}
        reverse = {family: assign_split(family) for family in reversed(families)}
        self.assertEqual(forward, reverse)
        self.assertEqual({v["split"] for v in forward.values()}, {"train","validation","test"})

    def test_paired_simulators_use_same_ancestry_assignment(self):
        records = [dict(assign_split("natural-valley"), simulator=sim, seed=seed)
                   for sim, seed in (("isaac", 1), ("gazebo", 729), ("isaac", 88))]
        self.assertTrue(validate_assignments(records)["valid"])
        records[1]["split"] = "test"
        self.assertFalse(validate_assignments(records)["valid"])

    def test_frozen_version_cannot_be_mutated(self):
        registry = copy.deepcopy(load_registry())
        registry["salt"] += "-changed"
        with self.assertRaises(ValueError):
            assign_split("new-world", registry)

    def test_custom_registry_requires_explicit_digest(self):
        registry = copy.deepcopy(load_registry())
        registry["version"] = "world-family-splits-v2"
        registry["salt"] += "-v2"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"registry.json"
            path.write_text(json.dumps(registry))
            with self.assertRaises(ValueError):
                load_registry(path)
            loaded = load_registry(path, registry_digest(registry))
            self.assertEqual(assign_split("example", loaded)["split_registry_version"],
                             "world-family-splits-v2")

    def test_cycles_and_variant_override_rejected(self):
        registry = copy.deepcopy(load_registry())
        registry["version"] = "test-registry"
        registry["family_aliases"] = {"a":"b", "b":"a"}
        with self.assertRaises(ValueError):
            assign_split("a", registry)
        registry["family_aliases"] = {"child":"parent"}
        registry["explicit_assignments"] = {"child":"test","parent":"train"}
        with self.assertRaises(ValueError):
            assign_split("child",registry)

    def test_missing_ancestry_rejected(self):
        for family in ("", " ", None):
            with self.assertRaises(ValueError):
                assign_split(family)

if __name__ == "__main__":
    unittest.main()

