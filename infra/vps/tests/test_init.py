"""Regression tests for repeatable VPS initialization; no Docker required."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("vps_init", Path(__file__).parents[1] / "init.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def read_env(root):
    return dict(line.split("=", 1) for line in (root / "shared/.env").read_text().splitlines()
                if "=" in line and not line.startswith("#"))


class InitializeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "deployment"
        # Avoid ownership changes and Windows read-only file semantics in tests.
        self.chown = patch.object(module.os, "chown", create=True).start()
        self.addCleanup(patch.stopall)
        patch.object(Path, "chmod", autospec=True).start()

    def initialize(self, release="release-one"):
        module.initialize(self.root, "travel.rainflow.foo", release)

    def test_generates_separate_secrets_and_no_implicit_admin(self):
        self.initialize()
        values = read_env(self.root)
        secrets = [values[key] for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET",
                                           "CREDENTIAL_ENCRYPTION_KEY", "BRIDGE_API_KEY")]
        self.assertEqual(len(set(secrets)), 5)
        self.assertTrue(all(len(value) == 64 for value in secrets))
        self.assertEqual(values["ADMIN_EMAILS"], "")
        self.assertIn("requirepass " + values["REDIS_PASSWORD"],
                      (self.root / "shared/redis.conf").read_text())

    def test_update_preserves_keys_and_postgres_ownership(self):
        self.initialize()
        before = read_env(self.root)
        providers = self.root / "shared/providers.env"
        providers.write_text("CUSTOM_PROVIDER=value\n")
        self.chown.reset_mock()
        self.initialize("release-two")
        after = read_env(self.root)
        for key, value in before.items():
            if key != "RELEASE_TAG":
                self.assertEqual(after[key], value)
        self.assertEqual(after["RELEASE_TAG"], "release-two")
        self.assertEqual(providers.read_text(), "CUSTOM_PROVIDER=value\n")
        self.assertFalse(any(call.args[0] == self.root / "shared/postgres"
                             for call in self.chown.call_args_list))

    def test_incomplete_existing_secrets_are_not_rotated(self):
        self.initialize()
        env = self.root / "shared/.env"
        env.write_text("JWT_SECRET=keep-this\n")
        with self.assertRaisesRegex(ValueError, "refusing to rotate"):
            self.initialize("release-two")
        self.assertEqual(env.read_text(), "JWT_SECRET=keep-this\n")

    def test_backend_provider_sync_copies_only_tavily_and_preserves_raw_values(self):
        self.initialize()
        shared = self.root / "shared"
        source = "TAVILY_API_KEY=test-$value#literal\nTRAVELMIND_TAVILY_BASE_URL=https://search.example.test/search\nGROK_API_KEY=never-copy\nGROK_MODEL=do-not-override-role-routing\nPOSTGRES_PASSWORD=not-a-provider\n"
        (shared / "providers.env").write_text(source)
        module.sync_backend_providers(shared)
        content = (shared / "backend-providers.env").read_text()
        self.assertIn("TAVILY_API_KEY=test-$value#literal\n", content)
        self.assertIn("TRAVELMIND_TAVILY_BASE_URL=", content)
        self.assertNotIn("GROK_", content)
        self.assertNotIn("POSTGRES", content)
        self.assertEqual((shared / "providers.env").read_text(), source)
        (shared / "providers.env").write_text("# revoked\n")
        module.sync_backend_providers(shared)
        self.assertNotIn("TAVILY_API_KEY=", (shared / "backend-providers.env").read_text())

    def test_travel_mcp_sync_is_backend_only_allowlisted_and_revocable(self):
        self.initialize()
        shared = self.root / "shared"
        private = shared / "travel-mcp.env"
        private.write_text("TRAVELMIND_HOTEL_MCP_ENABLED=true\nTRAVELMIND_HOTEL_MCP_TOKEN=mcp_fake_$literal\nTRAVELMIND_RAILWAY_MCP_URL=https://example.test/mcp\nTRAVELMIND_HOTEL_MCP_CONFIG_FILE=E:/private.json\nGROK_API_KEY=must-not-copy\n")
        module.sync_backend_providers(shared)
        content = (shared / "backend-providers.env").read_text()
        self.assertIn("TRAVELMIND_HOTEL_MCP_ENABLED=true\n", content)
        self.assertIn("TRAVELMIND_HOTEL_MCP_TOKEN=mcp_fake_$literal\n", content)
        self.assertIn("TRAVELMIND_RAILWAY_MCP_URL=https://example.test/mcp\n", content)
        self.assertNotIn("CONFIG_FILE", content)
        self.assertNotIn("GROK_API_KEY", content)
        self.assertNotIn("mcp_fake", (shared / "providers.env").read_text())
        private.write_text("# revoked\n")
        module.sync_backend_providers(shared)
        self.assertNotIn("TRAVELMIND_HOTEL_MCP_TOKEN", (shared / "backend-providers.env").read_text())

    def test_invalid_destination_rejected_before_writes(self):
        with self.assertRaises(ValueError):
            module.initialize(self.root, "https://travel.rainflow.foo", "release-one")
        self.assertFalse(self.root.exists())
        with self.assertRaises(ValueError):
            module.initialize(self.root, "travel.rainflow.foo", "../outside")
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
