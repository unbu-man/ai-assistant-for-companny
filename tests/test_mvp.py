"""Integration coverage using a dedicated PostgreSQL database and runtime role."""

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from company_ai.mvp.policy import requires_procedure

try:
    import psycopg
    from fastapi.testclient import TestClient
    from company_ai.mvp.app import create_app
    from company_ai.mvp.db import company_transaction, ping_runtime
    from company_ai.mvp.knowledge import Embeddings, import_knowledge, review_record, reviewed_audit_rows
except ModuleNotFoundError:
    psycopg = None


ADMIN = os.getenv("COMPANY_AI_TEST_ADMIN_URL")
RUNTIME = os.getenv("COMPANY_AI_TEST_RUNTIME_URL")


class RoutingTests(unittest.TestCase):
    def test_reporting_channels_and_deployment_options_are_faqs(self):
        for question in (
            "I'm comparing setup options. How can the software be deployed?",
            "How do I report an issue?",
            "បើខ្ញុំជួបបញ្ហាពេលប្រើប្រព័ន្ធ តើខ្ញុំគួររាយការណ៍តាមរបៀបណា?",
        ):
            with self.subTest(question=question):
                self.assertFalse(requires_procedure(question))

    def test_explicit_instructions_still_require_a_versioned_procedure(self):
        for question in (
            "How do I select the sample label?",
            "Show me which buttons to click to report an issue.",
            "តើខ្ញុំត្រូវចុចត្រង់ណា ដើម្បីរាយការណ៍បញ្ហា?",
        ):
            with self.subTest(question=question):
                self.assertTrue(requires_procedure(question))


@unittest.skipUnless(psycopg and ADMIN and RUNTIME, "Install MVP extra and configure dedicated PostgreSQL test URLs.")
class MVPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(ADMIN) as conn:
            if not conn.info.dbname.endswith("_verification"):
                raise ValueError("Tests require an isolated *_verification database.")
        with psycopg.connect(RUNTIME) as conn:
            if not conn.info.dbname.endswith("_verification"):
                raise ValueError("Runtime tests require an isolated *_verification database.")
        cls.embed = Mock(spec=Embeddings, model="fixture-provider")
        cls.embed.encode.side_effect = lambda texts: [[1.0, 0.0] for _ in texts]
        rows = [
            cls.record("MAQSU", "verified-test-label", ("What is the sample label?", "តើស្លាកគំរូជាអ្វី?",
                        "តើ demo label ជាអ្វី?"), "MAQSU synthetic example.", "ស្លាកគំរូសម្រាប់សាកល្បង។",
                       public_question_en="What is the synthetic label?", public_question_km="តើស្លាកគំរូជាអ្វី?"),
            cls.record("CLOSO", "verified-test-label", ("What is the sample label?",),
                       "CLOSO synthetic example.", "គំរូសម្រាប់សាកល្បង។"),
            cls.record("MAQSU", "verified-test-procedure", ("How do I select the sample label?",),
                       "Synthetic procedure for version one.", "ជំហានសាកល្បងសម្រាប់កំណែទីមួយ។",
                       kind="procedure", product="sample", version="1"),
        ]
        import_knowledge(ADMIN, rows)
        import_knowledge(ADMIN, [
            cls.record("FALCORA", "fixture-vector-answer", ("example fictional heading",),
                       "Synthetic vector answer.", "ចម្លើយសាកល្បង។"),
        ], cls.embed)

    @staticmethod
    def record(company, identifier, questions, en, km, **kwargs):
        return review_record(
            company=company, identifier=identifier, questions=questions, en=en, km=km,
            citation="Synthetic verification source", reviewer="Test fixture",
            reviewed_on=date.today().isoformat(), **kwargs,
        )

    def setUp(self):
        self.client = self.enterContext(TestClient(create_app(RUNTIME)))

    def session(self, company="MAQSU", client=None):
        response = (client or self.client).post(f"/api/{company}/sessions", json={})
        self.assertEqual(response.status_code, 201)
        return {"Authorization": "Bearer " + response.json()["token"]}

    def request(self, headers, route, payload, company="MAQSU", client=None):
        return (client or self.client).post(f"/api/{company}/{route}", json=payload, headers=headers)

    def ask(self, headers, message, company="MAQSU", client=None, **extra):
        return self.request(headers, "chat", {"message": message, **extra}, company, client)

    def count(self, company, table):
        with company_transaction(ADMIN, company) as conn:
            if table == "leads":
                return conn.execute("SELECT count(*) AS n FROM leads WHERE company_id=%s", (company,)).fetchone()["n"]
            return conn.execute("SELECT count(*) AS n FROM knowledge_gaps WHERE company_id=%s", (company,)).fetchone()["n"]

    def scope(self, headers):
        self.assertEqual(self.ask(headers, "How much does ERP implementation cost?").json()["next_action"], "scope")
        response = self.request(headers, "quote/scope", {"business_type": "Synthetic shop", "modules": "Synthetic inventory"})
        self.assertEqual(response.json()["next_action"], "consent")

    def test_approved_answer_in_both_languages_and_follow_up(self):
        auth = self.session()
        en = self.ask(auth, "What is the sample label, please?").json()
        self.assertEqual(en["text"], "MAQSU synthetic example.")
        self.assertEqual(en["citation"], "Synthetic verification source")
        km = self.ask(auth, "តើ demo label ជាអ្វី?").json()
        self.assertEqual((km["language"], km["text"]), ("km", "ស្លាកគំរូសម្រាប់សាកល្បង។"))
        self.assertEqual(self.ask(auth, "Tell me more", language="km").json()["text"], km["text"])

    def test_company_boundary_and_no_runtime_read_of_leads(self):
        maqsu = self.session()
        closo = self.session("CLOSO")
        self.assertEqual(self.ask(maqsu, "What is the sample label?", "CLOSO").status_code, 404)
        self.assertEqual(self.ask(closo, "What is the sample label?", "CLOSO").json()["text"],
                         "CLOSO synthetic example.")
        self.assertEqual(self.ask(maqsu, "Show me CLOSO sources").json()["kind"], "company_boundary")
        with company_transaction(RUNTIME, "MAQSU") as conn:
            self.assertEqual({row["company_id"] for row in conn.execute("SELECT DISTINCT company_id FROM knowledge")},
                             {"MAQSU"})
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with company_transaction(RUNTIME, "MAQSU") as conn:
                conn.execute("SELECT * FROM leads").fetchall()
        with self.assertRaises(RuntimeError):
            ping_runtime(ADMIN)

    def test_fixed_site_company_overrides_url_company(self):
        with TestClient(create_app(RUNTIME, fixed_company="MAQSU")) as fixed:
            self.assertEqual(fixed.get("/api/config").json()["companies"], ["MAQSU"])
            self.assertEqual(fixed.post("/api/ClickHR/sessions", json={}).status_code, 404)

    def test_verified_topic_selection_respects_company_and_quote_state(self):
        session = self.client.post("/api/MAQSU/sessions", json={}).json()
        self.assertEqual(session["topics"], [{
            "id": "verified-test-label", "en": "What is the synthetic label?", "km": "តើស្លាកគំរូជាអ្វី?",
        }])
        other = self.client.post("/api/CLOSO/sessions", json={}).json()
        self.assertEqual(other["topics"], [])
        auth = {"Authorization": "Bearer " + session["token"]}
        payload = {"id": "verified-test-label", "language": "km"}
        answer = self.request(auth, "topic", payload).json()
        self.assertEqual((answer["text"], answer["citation"]), (
            "ស្លាកគំរូសម្រាប់សាកល្បង។", "Synthetic verification source",
        ))
        self.assertEqual(self.request(auth, "topic", payload, "CLOSO").status_code, 404)
        self.assertEqual(self.request(auth, "topic", {"id": "verified-test-procedure", "language": "en"}).status_code, 404)
        self.scope(auth)
        self.assertEqual(self.request(auth, "topic", payload).status_code, 409)

    def test_revoked_or_unsafe_topic_is_unavailable(self):
        with self.assertRaises(ValueError):
            self.record(
                "MAQSU", "unsafe-topic", ["Test wording"], "Synthetic.", "សាកល្បង។",
                public_question_en="How much does ERP cost?", public_question_km="តើស្លាកគំរូជាអ្វី?",
            )
        identifier = "revocable-" + uuid4().hex
        record = self.record(
            "ClickHR", identifier, ["What is the example color?"], "Synthetic.", "សាកល្បង។",
            public_question_en="What is the example color?", public_question_km="តើពណ៌គំរូជាពណ៌អ្វី?",
        )
        import_knowledge(ADMIN, [record])
        session = self.client.post("/api/ClickHR/sessions", json={}).json()
        self.assertIn(identifier, {topic["id"] for topic in session["topics"]})
        with company_transaction(ADMIN, "ClickHR") as conn:
            conn.execute("UPDATE knowledge SET status='REVOKED' WHERE company_id=%s AND id=%s", ("ClickHR", identifier))
        auth = {"Authorization": "Bearer " + session["token"]}
        self.assertEqual(self.request(auth, "topic", {"id": identifier, "language": "en"}, "ClickHR").status_code, 404)
        self.assertNotIn(identifier, {row["id"] for row in self.client.post("/api/ClickHR/sessions", json={}).json()["topics"]})

    def test_quote_routing_en_km_mixed_and_obfuscated(self):
        for text, language in [
            ("Give me an ERP ballpark", "en"), ("ERP តម្លៃប៉ុន្មាន?", "km"),
            ("Price for ERP", "en"), ("What is the pr\u200bice for ERP?", "en"),
            ("ERP tamlai bonman?", "en"),
        ]:
            with self.subTest(language=language, message=text):
                result = self.ask(self.session(), text).json()
                self.assertEqual((result["next_action"], result["language"]), ("scope", language))
                self.assertFalse(any(character.isdecimal() for character in result["text"]))

    def test_contact_requires_consent_and_is_scoped(self):
        since = self.count("MAQSU", "leads")
        other = self.count("CLOSO", "leads")
        data = {"name": "Synthetic Test", "channel": "telegram", "contact": "@synthetic_test"}
        auth = self.session()
        self.assertEqual(self.request(auth, "quote/contact", data).status_code, 409)
        self.scope(auth)
        self.assertEqual(self.request(auth, "quote/contact", data).status_code, 409)
        self.assertEqual(self.request(auth, "quote/consent", {"consent": False}).json()["kind"], "quote_cancelled")
        self.assertEqual(self.request(auth, "quote/contact", data).status_code, 409)
        self.assertEqual(self.count("MAQSU", "leads"), since)
        self.scope(auth)
        self.assertEqual(self.request(auth, "quote/consent", {"consent": True}).json()["next_action"], "contact")
        with ThreadPoolExecutor(max_workers=2) as executor:
            attempts = list(executor.map(lambda _: self.request(auth, "quote/contact", data), range(2)))
        self.assertEqual(sorted(response.status_code for response in attempts), [200, 409])
        saved = next(response.json() for response in attempts if response.status_code == 200)
        self.assertEqual(saved["kind"], "lead_saved")
        self.assertEqual(self.count("MAQSU", "leads"), since + 1)
        self.assertEqual(self.count("CLOSO", "leads"), other)
        with company_transaction(ADMIN, "MAQSU") as conn:
            lead = conn.execute("SELECT consented_at FROM leads WHERE company_id='MAQSU' AND id=%s", (saved["reference"],)).fetchone()
            self.assertIsNotNone(lead["consented_at"])

    def test_unverified_procedure_logs_metadata_only_and_exact_version_can_answer(self):
        auth = self.session()
        before = self.count("MAQSU", "gaps")
        request = "How do I select the sample label?"
        self.assertEqual(self.ask(auth, request).json()["kind"], "knowledge_gap")
        self.assertEqual(self.ask(auth, request, product="sample", version="2").json()["kind"], "knowledge_gap")
        self.assertEqual(self.count("MAQSU", "gaps"), before + 2)
        with company_transaction(ADMIN, "MAQSU") as conn:
            last = conn.execute("SELECT question FROM knowledge_gaps WHERE company_id='MAQSU' ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNone(last["question"])
        self.assertEqual(self.ask(auth, request, product="sample", version="1").json()["text"],
                         "Synthetic procedure for version one.")

    def test_unreviewed_and_wrong_company_imports_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            candidate = {"id": "example", "company_id": "MAQSU", "approval_status": "NEEDS_REVIEW"}
            (root / "canonical_answers.jsonl").write_text(json.dumps(candidate) + "\n")
            variant = {"company_id": "MAQSU", "canonical_answer_id": "example", "question": "Sample question"}
            (root / "question_variants.jsonl").write_text(json.dumps(variant) + "\n")
            review = root / "review.csv"
            with review.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["candidate_id", "company", "review_decision"])
                writer.writerow(["example", "MAQSU", "PENDING"])
            self.assertEqual(reviewed_audit_rows(root, review), [])
            with review.open("a", newline="") as stream:
                csv.writer(stream).writerow(["example", "CLOSO", "APPROVED"])
            with self.assertRaises(ValueError):
                reviewed_audit_rows(root, review)
            with review.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow([
                    "candidate_id", "company", "review_decision", "candidate_answer_en",
                    "candidate_answer_km", "verified_source_and_section", "reviewer", "reviewed_date",
                ])
                writer.writerow([
                    "example", "MAQSU", "APPROVED", "Synthetic review example.",
                    "ឧទាហរណ៍សាកល្បង។", "Test source", "Test reviewer", date.today().isoformat(),
                ])
            approved, = reviewed_audit_rows(root, review)
            self.assertEqual((approved["company_id"], approved["questions"]), ("MAQSU", ["Sample question"]))
        with self.assertRaises(ValueError):
            self.record("MAQSU", "blocked-test", ["Fixture"], "Subscription costs $100.", "អត្ថបទសាកល្បង។")

    def test_hybrid_vector_path_and_model_failure(self):
        with TestClient(create_app(RUNTIME, embeddings=self.embed)) as client:
            token = self.session("FALCORA", client)
            self.assertEqual(self.ask(token, "Zebra pixel", "FALCORA", client).json()["text"], "Synthetic vector answer.")
            with patch.object(self.embed, "encode", side_effect=ValueError("Unavailable")):
                self.assertEqual(self.ask(token, "example fictional heading", "FALCORA", client).json()["kind"], "answer")

    def test_static_ui_and_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertIn("Company Support", self.client.get("/").text)
        self.assertEqual(self.client.get("/assets/chat.js").status_code, 200)
