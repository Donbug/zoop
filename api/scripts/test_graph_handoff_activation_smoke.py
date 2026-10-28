"""Focused fixture isolation checks; run with pipeline Python and unittest discovery."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import graph_handoff_activation_smoke as smoke


class IsolationTest(unittest.TestCase):
    def test_child_allowlist_drops_credentials_borrowed_db_and_operator_bypass(self):
        source = {
            "PATH": "/usr/bin:/bin", "HOME": "/synthetic", "DOCKER_CONTEXT": "orbstack",
            "PROVIDER_SECRET": "synthetic-test-value", "OPENAI_API_KEY": "synthetic-test-value",
            "TYPESAFE_API_KEY": "synthetic-test-value", "AWS_SESSION_TOKEN": "synthetic-test-value",
            "DB_URL": "jdbc:postgresql://borrowed.invalid/db", "DB_PASSWORD": "synthetic-test-value",
            "SPRING_APPLICATION_JSON": "{}", "JAVA_TOOL_OPTIONS": "-Dsynthetic=true",
            "DOCKER_HOST": "tcp://remote.invalid:2375",
            "ZOOP_GRAPH_ACTIVATION_ALLOW_WITHOUT_EXCLUSION_STORE": "true",
        }
        self.assertEqual(smoke.isolated_environment(source),
                         {"PATH": "/usr/bin:/bin", "HOME": "/synthetic", "DOCKER_CONTEXT": "orbstack"})

    def test_fixture_java_clients_are_disabled_even_with_inherited_flags(self):
        db = SimpleNamespace(user="synthetic", password="synthetic-local-only")
        jar = smoke.FixtureJar("java", Path("synthetic.jar"), db, None)
        with patch.dict(os.environ, {"DB_URL": "jdbc:postgresql://127.0.0.1:1/synthetic",
                                     "ZOOP_AI_CLIENT_ENABLED": "true",
                                     "ZOOP_GRAPH_ACTIVATION_ALLOW_WITHOUT_EXCLUSION_STORE": "true"}, clear=True):
            env = jar.base_env()
        for flag in smoke.DISABLED:
            self.assertEqual(env[flag], "false")
        self.assertNotIn("ZOOP_GRAPH_ACTIVATION_ALLOW_WITHOUT_EXCLUSION_STORE", env)
        self.assertNotIn("SPRING_APPLICATION_JSON", env)

    def test_publication_snapshot_covers_real_contract_tables_and_revisions(self):
        class Database:
            def __init__(self):
                self.queries = []

            def scalar(self, query):
                self.queries.append(query)
                return "synthetic-version"

            def rows(self, query):
                self.queries.append(query)
                return []

        db = Database()
        state = smoke.publication_state(db)
        self.assertEqual(state["active"], "synthetic-version")
        self.assertTrue(any("review_revision" in query and "published_at" in query for query in db.queries))
        self.assertTrue(any("idempotency_records" in query for query in db.queries))
        self.assertTrue(any("graph.version.activate" in query for query in db.queries))
        self.assertFalse(any("admin_sessions" in query for query in db.queries))


if __name__ == "__main__":
    unittest.main()
