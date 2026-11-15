"""R9: discoverable plugin UI is read-only and never gains L3 Apply rights."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import backlot.server as server


class PluginCatalogApiTests(unittest.TestCase):
    def test_registered_catalog_and_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root=Path(tmp)/"projects"
            (project_root/"demo").mkdir(parents=True)
            with patch.object(server,"PROJECTS_DIR",project_root):
                with TestClient(server.create_app()) as client:
                    catalog=client.get("/api/evedirector/plugins")
                    self.assertEqual(catalog.status_code,200)
                    result=catalog.json()
                    self.assertEqual(result["schema"],"evedirector.plugin_catalog.v1")
                    self.assertFalse(result["runtime_execution_allowed_by_api"])
                    self.assertFalse(result["canonical_write"])
                    self.assertEqual({x["plugin_id"] for x in result["plugins"]},{"evoe","ordr","native-r0"})
                    ui=client.get("/p/demo/plugins")
                    self.assertEqual(ui.status_code,200)
                    self.assertIn("AI Drawing Plugin Hub",ui.text)
                    self.assertIn("/ui/plugin-hub.js",ui.text)
                    self.assertEqual(client.get("/p/missing/plugins").status_code,404)
                    self.assertEqual(client.post("/api/evedirector/plugins",json={}).status_code,405)
                    self.assertEqual(client.post("/api/evedirector/plugins/evoe/run",json={}).status_code,404)
                    self.assertEqual(client.post("/api/evedirector/plugins/ordr/canonical-write",json={}).status_code,404)

    def test_old_l4_review_still_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root=Path(tmp)/"projects"; (project_root/"demo").mkdir(parents=True)
            with patch.object(server,"PROJECTS_DIR",project_root):
                with TestClient(server.create_app()) as client:
                    detail=client.get("/p/demo/agent-review")
                    self.assertEqual(detail.status_code,200)
                    self.assertIn("agent-review.js",detail.text)


if __name__ == "__main__":unittest.main()
