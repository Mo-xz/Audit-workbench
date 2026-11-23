"""Every command a frontend button sends is one the registry knows.

The APM page's Regenerate sent ``plan_engagement``, a command that was never
registered, and every click failed with "Unknown command" — nothing on either
side noticed, because the id is a string literal in a Vue file and the registry
is a Python dict. This reads the one against the other.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.agent import commands

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
SENT = re.compile(r"\{\s*command:\s*'([a-z_]+)',\s*source:")


def test_every_command_a_button_sends_is_registered():
    sent = {
        (path.relative_to(FRONTEND).as_posix(), match.group(1))
        for path in [*FRONTEND.rglob("*.vue"), *FRONTEND.rglob("*.ts")]
        if not path.name.endswith(".test.ts")
        for match in SENT.finditer(path.read_text(encoding="utf-8"))
    }
    assert sent, "the scan found no command a button sends"
    unknown = sorted((where, command) for where, command in sent if command not in commands.COMMANDS)
    assert unknown == []
