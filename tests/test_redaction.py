"""Acceptance test 2: no name, college or email reaches the LLM payload."""
import ast
import json

from conftest import IDENTITY, ROOT, FakeClassifier, write_cv_docx
from shortlister import pipeline, vault


def test_payload_has_no_identity(env):
    write_cv_docx(env / "applications" / "cv_priya_raghavan_pm.docx")
    fake = FakeClassifier()
    pipeline.run_batch(classifier=fake, log=lambda *_: None)

    assert len(fake.payloads) == 1
    blob = json.dumps(fake.payloads[0], ensure_ascii=False).lower()
    for value in [IDENTITY["name"], *IDENTITY["name"].split(), IDENTITY["email"], "98765 43210",
                  *IDENTITY["colleges"], "Narsee", "Jamnabai", "IIT"]:
        assert value.lower() not in blob, f"{value!r} leaked into the LLM payload"
    for value in ["14/03/1994", "female", "married", "sunshine chs", "400058", "sv road"]:
        assert value not in blob, f"{value!r} leaked into the LLM payload"
    # the file name carries the name too; it must not be sent
    assert "cv_priya" not in blob
    # City is kept for the relocation question
    assert "mumbai" in blob


def test_identity_goes_to_vault_only(env):
    write_cv_docx(env / "applications" / "cv_priya_raghavan_pm.docx")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    ident = vault.get("KG-0001")
    assert ident["name"] == IDENTITY["name"]
    assert ident["email"] == IDENTITY["email"]


def test_scoring_step_never_reads_the_vault():
    """G4.3: llm.py and scoring.py must not import the vault module."""
    for mod in ("llm.py", "scoring.py"):
        tree = ast.parse((ROOT / "shortlister" / mod).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names |= {a.name for a in node.names} | {node.module or ""}
            elif isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
        assert not any("vault" in n for n in names), f"{mod} imports the vault"
        assert "identities.json" not in (ROOT / "shortlister" / mod).read_text(encoding="utf-8")
