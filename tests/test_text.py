"""Checks on every piece of text a family sees.

1. Every key exists in English, Tamil and Hindi.
2. Every reason, action, rule and summary code the engine can produce has text.
3. House style: no hyphens, dashes or emojis anywhere in the copy, so it reads like a person wrote it.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_parity import NODE

ROOT = Path(__file__).resolve().parent.parent
ENGINE_JS = (ROOT / "static" / "engine.js").read_text(encoding="utf-8")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF️]")


@pytest.fixture(scope="module")
def dicts():
    out = subprocess.run([NODE, str(ROOT / "scripts" / "dump_i18n.js")], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(not Path(NODE).exists(), reason="node not installed")
def test_all_languages_have_every_key(dicts):
    en = set(dicts["en"])
    for code in ("ta", "hi"):
        assert set(dicts[code]) == en, (code, sorted(en ^ set(dicts[code])))


@pytest.mark.skipif(not Path(NODE).exists(), reason="node not installed")
def test_every_engine_code_has_text(dicts):
    codes = set(re.findall(r'"((?:LIST_I|SERVICE|AMBULANCE|TOILETRY|ROOM|ICU|PD|ACT|R|SUM)_[A-Z_]+)"', ENGINE_JS))
    codes = {c for c in codes if not c.endswith("_") and c != "ACT_SUBSUMED"}  # string prefixes, not codes
    codes |= {"SUBSUMED_ROOM", "SUBSUMED_PROCEDURE", "SUBSUMED_TREATMENT",
              "ACT_SUBSUMED_ROOM", "ACT_SUBSUMED_PROCEDURE", "ACT_SUBSUMED_TREATMENT"}
    rules = json.loads((ROOT / "static" / "rules.json").read_text())
    codes |= {g["rule"] for g in rules["groups"]}
    missing = sorted(c for c in codes if c not in dicts["en"])
    assert not missing, missing


@pytest.mark.skipif(not Path(NODE).exists(), reason="node not installed")
def test_house_style_no_hyphens_dashes_or_emoji(dicts):
    bad = []
    for code, d in dicts.items():
        for key, text in d.items():
            if re.search(r"[\-‐-―]", text) or EMOJI.search(text):
                bad.append((code, key, text))
    assert not bad, bad
