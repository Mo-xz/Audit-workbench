"""The planning memorandum's data-analytics section, taken from the EDA memo.

The memorandum used to have a model restate the memo in its own words: a
paraphrase of a document the engagement already holds, without its exhibits,
and out of date the moment the memo was rewritten. This module puts the memo's
own parts there instead — its lead, what was received, the profile sections
and their exhibits, the findings, the reliance, the implications and what the
data cannot answer — demoted one heading level under ``Data analytics
performed`` and fenced by markers that record which memo they were taken from.

Three readers, three forms:

* the page draws the section as written, exhibits and all;
* a model reads :func:`for_model`, in which the block is a compact digest —
  the memorandum is already longer than some planning budgets, and pasting the
  memo whole would push the risks after it out of every planning turn;
* :func:`state` tells the page whether the memo has moved since, so the
  section is refreshed by asking (:func:`splice`), never behind the auditor.

Pure: no workspace, no I/O. The callers hold the memo and the memorandum.
"""

from __future__ import annotations

import hashlib
import re

from . import markdown_sections
from .analysis_memo import flatten_embeds

SECTION = "Data analytics performed"

#: The memo's sections the memorandum reproduces, in the memo's order. Further
#: work is the analysis' own to-do list; the memorandum plans its own.
TAKEN = (
    "Data received and its limitations",
    "Where the value is",
    "How the process runs",
    "People and authority",
    "What the analysis found",
    "How far these results can be relied on",
    "Implications for the plan",
    "What the data cannot answer",
)

_OPEN = re.compile(r"<!--\s*analytics-from-memo:([0-9a-f]+)\s*-->")
_CLOSE = "<!-- /analytics-from-memo -->"
_BLOCK = re.compile(r"<!--\s*analytics-from-memo:([0-9a-f]+)\s*-->.*?<!--\s*/analytics-from-memo\s*-->", re.DOTALL)
_FENCE = re.compile(r"^(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})(\s+.*)$")

#: The digest a model reads in the block's place is capped, so a long memo can
#: never crowd the memorandum's own risks out of a planning budget.
MAX_DIGEST_CHARACTERS = 6_000


def memo_sha(memo_markdown: str) -> str:
    """The memo's identity as the section records it."""
    return hashlib.sha1(str(memo_markdown or "").strip().encode("utf-8")).hexdigest()[:12]


def _memo_sections(memo_markdown: str) -> tuple[str, dict[str, str]]:
    """The memo's lead and its ``##`` sections by heading."""
    lead_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    fenced = False
    for line in str(memo_markdown or "").splitlines():
        if _FENCE.match(line.strip()):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            current = sections.setdefault(line[3:].strip(), [])
            continue
        (lead_lines if current is None else current).append(line)
    return "\n".join(lead_lines).strip(), {key: "\n".join(value).strip() for key, value in sections.items()}


def _demoted(body: str, by: int) -> str:
    """Every heading outside a fence, ``by`` levels deeper."""
    out: list[str] = []
    fenced = False
    for line in body.splitlines():
        if _FENCE.match(line.strip()):
            fenced = not fenced
        match = None if fenced else _HEADING.match(line)
        out.append(f"{'#' * min(6, len(match.group(1)) + by)}{match.group(2)}" if match else line)
    return "\n".join(out)


def transclusion(memo_markdown: str) -> str:
    """The section body the memorandum carries, between its markers."""
    lead, sections = _memo_sections(memo_markdown)
    parts = [f"<!-- analytics-from-memo:{memo_sha(memo_markdown)} -->"]
    if lead:
        parts.append(lead)
    for heading in TAKEN:
        body = sections.get(heading)
        if body:
            parts.append(f"### {heading}\n\n{_demoted(body, 1)}")
    parts.append(_CLOSE)
    return "\n\n".join(parts)


def splice(apm_markdown: str, memo_markdown: str) -> str:
    """The memorandum with its analytics section taken from this memo.

    A memorandum without the section is returned unchanged: the template
    declares it, and a memorandum that dropped it is the auditor's to restore.
    """
    if not str(memo_markdown or "").strip():
        return apm_markdown
    try:
        return markdown_sections.replace_bodies(apm_markdown, {SECTION: transclusion(memo_markdown)})
    except ValueError:
        return apm_markdown


def state(apm_markdown: str, memo_markdown: str) -> str:
    """``none`` (the section is written prose), ``current``, ``stale`` or ``orphaned``."""
    match = _OPEN.search(str(apm_markdown or ""))
    if match is None:
        return "none"
    if not str(memo_markdown or "").strip():
        return "orphaned"
    return "current" if match.group(1) == memo_sha(memo_markdown) else "stale"


def _digest(block: str, titles: dict[str, str] | None) -> str:
    """What a model reads in the block's place: the argument, not the exhibits."""
    inner = _OPEN.sub("", block).replace(_CLOSE, "")
    lines = flatten_embeds(inner, titles).splitlines()
    out: list[str] = []
    section = ""
    paragraph_taken = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            section = stripped[4:].strip()
            paragraph_taken = False
            continue
        if not stripped or stripped.startswith("|") or stripped.startswith("_See analysis"):
            if not stripped and out and out[-1] != "":
                out.append("")
            continue
        if section == "":
            out.append(stripped)  # the memo's lead, whole
        elif section == "What the analysis found":
            if stripped.startswith("####"):
                out.append(f"- Finding: {stripped.lstrip('#').strip()}")
        elif section in ("Implications for the plan", "What the data cannot answer"):
            if not paragraph_taken:
                out.append(f"{section}:")
                paragraph_taken = True
            out.append(stripped)
        elif not paragraph_taken:
            # One paragraph of each descriptive section: what it says the data is.
            out.append(f"{section}: {stripped}")
            paragraph_taken = True
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    if len(text) > MAX_DIGEST_CHARACTERS:
        text = text[: MAX_DIGEST_CHARACTERS - 1].rsplit("\n", 1)[0] + "\n…"
    return (
        "_This section reproduces the engagement's analysis memo, with its exhibits, "
        "on the page. In summary:_\n\n" + text
    )


def for_model(apm_markdown: str, titles: dict[str, str] | None = None) -> str:
    """The memorandum as a model should read it: the memo block as its digest."""
    text = str(apm_markdown or "")
    if not _OPEN.search(text):
        return text
    return _BLOCK.sub(lambda match: _digest(match.group(0), titles), text)


__all__ = [
    "MAX_DIGEST_CHARACTERS",
    "SECTION",
    "TAKEN",
    "for_model",
    "memo_sha",
    "splice",
    "state",
    "transclusion",
]
