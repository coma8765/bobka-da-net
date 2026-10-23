import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_flow import build  # noqa: E402


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((ROOT / "nifi/lr8-delivery-import.json").read_text())
        self.flow = self.snapshot["flowContents"]

    def test_export_is_reproducible(self):
        self.assertEqual(build(), self.snapshot)

    def test_references_and_required_processors(self):
        processors = {p["identifier"]: p for p in self.flow["processors"]}
        services = {s["identifier"] for s in self.flow["controllerServices"]}
        classes = {p["type"].rsplit(".", 1)[-1] for p in processors.values()}
        self.assertTrue(
            {
                "GetFile",
                "ConvertRecord",
                "SplitJson",
                "PutDatabaseRecord",
                "LogAttribute",
                "ValidateRecord",
                "MergeContent",
            }.issubset(classes)
        )
        edges = set()
        for c in self.flow["connections"]:
            source, dest = c["source"]["id"], c["destination"]["id"]
            self.assertIn(source, processors)
            self.assertIn(dest, processors)
            self.assertGreater(c["backPressureObjectThreshold"], 0)
            self.assertEqual(c["flowFileExpiration"], "0 sec")
            for rel in c["selectedRelationships"]:
                self.assertNotIn(rel, processors[source]["autoTerminatedRelationships"])
                self.assertNotIn((source, rel, dest), edges)
                edges.add((source, rel, dest))
        for p in processors.values():
            for key, desc in p["propertyDescriptors"].items():
                if desc.get("identifiesControllerService"):
                    self.assertIn(p["properties"][key], services)

    def test_committed_flow_cannot_return_to_insert(self):
        by_name = {p["name"]: p["identifier"] for p in self.flow["processors"]}
        edges = {}
        for c in self.flow["connections"]:
            edges.setdefault(c["source"]["id"], set()).add(c["destination"]["id"])
        seen, pending = set(), [by_name["Mark committed"]]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(edges.get(current, ()))
        self.assertNotIn(by_name["Insert whole file"], seen)
        self.assertIn(by_name["Log loaded"], seen)
        self.assertNotIn(by_name["Log rejected"], seen)

    def test_export_has_no_password(self):
        params = self.snapshot["parameterContexts"]["lr8"]["parameters"]
        password = next(p for p in params if p["name"] == "jdbc.password")
        self.assertTrue(password["sensitive"])
        self.assertFalse(password.get("value"))
        db = next(
            s
            for s in self.flow["controllerServices"]
            if s["name"] == "PostgreSQL supply_lab"
        )
        self.assertEqual(db["properties"]["Password"], "#{jdbc.password}")


if __name__ == "__main__":
    unittest.main()
