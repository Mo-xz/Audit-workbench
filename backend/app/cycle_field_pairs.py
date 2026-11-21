"""Field pairs a cycle's documents probably share, found by name.

Which field of one document corresponds to which field of another is a property
of the schemas, not of any requirement: a goods receipt's ``quantity_received``
is the purchase order's ``quantity`` whatever the matrix says about matching.
A proposal turn asked to write the cycle's assertions from the requirements'
words wrote what the words named — "agree with the approved requisition" got
four comparisons, "matched to the order and the receipt" got reference checks —
and never compared the receipt's quantity with the order's, which is the one
comparison that finds goods billed and paid for but not delivered.

So the pairs are proposed here, from the schemas alone, and the proposal turn
reviews them: a pair it does not decline, with a reason, becomes an assertion.
Its worst case is this floor. Everything here is pure — no workspace, no
values — so the prompt and the validator compute exactly the same list.

What a name match can and cannot do was measured on the shipped engagements.
It finds receipt quantity against order quantity, and treasury's rate,
counterparty, value date and maturity date. It cannot find two fields that use
different words for one value — a deal's ``principal`` and a confirmation's
``amount`` — which is why the fields left without a candidate are listed
separately, for the turn to pair where they state the same thing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from .currencies import ISO_CURRENCIES, WORD_CODES

# Words that say what kind of thing a field is without saying which value it
# holds. Generic English and record-keeping words only: a word specific to an
# industry or a currency is a real signal, and the review declines the pairs it
# makes in error.
STOPWORDS = frozenset({
    "a", "an", "and", "at", "by", "code", "date", "for", "id", "in", "name",
    "no", "number", "of", "on", "or", "ref", "reference", "status", "the",
    "to", "type",
})

# A pair of dates sharing a word is almost never two statements of one date —
# a due date and a payment date share "payment" and must differ. Dates enter
# the floor only under the same name; the rest are listed as unpaired.
NAME_ONLY_VALUE_TYPES = frozenset({"date"})

# Value types a field must have to be listed as unpaired. A text attribute
# with no counterpart is usually a narrative, which no other document restates.
UNPAIRED_VALUE_TYPES = frozenset({"amount", "number", "date"})

# Value types that pair with each other as well as with themselves. A sum of
# money typed ``number`` on one document and ``amount`` on the next is one
# misjudged type, not two different facts, and the names still have to agree.
_NUMERIC = frozenset({"amount", "number"})


def _compatible(left: str, right: str) -> bool:
    return left == right or (left in _NUMERIC and right in _NUMERIC)

# A large engagement can propose more pairs than a turn can review well. The
# floor keeps the strongest, same-name first, and says how many it left out.
MAX_CANDIDATES = 80

# Words that name one thing in different houses' vocabularies, mapped to one
# spelling before names are compared. Generic accounting words only, the same
# bar as the stopwords: an invoice calling its counterparty the supplier and
# an order calling it the vendor is the common case, and so is a purchase
# order's ``po_total`` restated as an invoice's ``invoice_amount``.
SYNONYMS = {
    "supplier": "vendor",
    "total": "amount",
    "sum": "amount",
    "value": "amount",
}

# A currency code says what a figure is denominated in, not which figure it
# is: "PKR" in a requisition's "Estimated total cost (PKR)" and an order's
# "PO total (PKR)" is not a reason to pair them. The currency travels with an
# amount's value instead.
_CURRENCY_WORDS = frozenset(code.lower() for code in ISO_CURRENCIES) - WORD_CODES

_RULE_ID = re.compile(r"[^a-z0-9]+")


def _words(text: object) -> set[str]:
    return {
        word
        for word in re.split(r"[^a-z0-9]+", str(text or "").lower())
        if word and word not in STOPWORDS
    }


def _rule_id(*parts: str) -> str:
    joined = "_".join(_RULE_ID.sub("_", part.lower()).strip("_") for part in parts)
    joined = re.sub(r"_+", "_", joined).strip("_")
    return f"pair_{joined}"


def _eligible(field: Mapping[str, object]) -> bool:
    """A field whose value another document might restate.

    Not an identifier: two records sharing a reference is a join, and the join
    keys already state those. Not a control: a signature, an approver, a
    checkbox records who performed one step on one document, and a different
    document's control is a different step.
    """

    return str(field.get("role") or "") not in {"identifier", "control"}


def positions(roles: Sequence[Mapping[str, object]]) -> list[tuple[str, str]]:
    """One role per document type, as ``(role, document_type)`` in cycle order.

    Roles sharing a document type are positions of one record kind — a
    requisition raised, verified and financially approved is one requisition —
    and a pair between them is a field compared with itself. The *last* such
    role is the record in its final state, which is the one a later document
    has to preserve.
    """

    chosen: dict[str, str] = {}
    order: list[str] = []
    for role in roles:
        name = str(role.get("name") or "")
        document_type = str(role.get("document_type") or "")
        if not name or not document_type:
            continue
        if document_type not in chosen:
            order.append(document_type)
        chosen[document_type] = name
    return [(chosen[document_type], document_type) for document_type in order]


def candidates(
    schemas: Iterable[Mapping[str, object]],
    roles: Sequence[Mapping[str, object]],
) -> dict:
    """Pairs of fields across the cycle's document types that share a name.

    Returns ``{"pairs": [...], "omitted": n}``. Each pair is
    ``{id, left: {role, field}, right: {role, field}, value_type, basis, words}``
    where ``basis`` is ``same_name`` or ``shared_word``.

    Compatible value types on both sides — the same one, or ``amount`` with
    ``number`` — and a name either identical or sharing a
    word once generic words and the words of the field's own document type
    are set aside — "invoice" in an invoice's ``invoice_currency`` says which
    document, not which value. Only its own: "vendor" names an invoice type
    and is still the word that pairs a requisition's ``proposed_vendor`` with
    an order's ``vendor_name``. For each field only its strongest matches on the other
    document are kept, and ties are all kept: keeping one of a tie chose
    ``bank_name`` over ``counterparty`` for a confirmation's
    ``counterparty_bank``, which would have hidden a deal booked against the
    wrong counterparty.
    """

    by_type = {
        str(item.get("document_type") or ""): [
            field for field in item.get("fields") or [] if isinstance(field, Mapping)
        ]
        for item in schemas
        if isinstance(item, Mapping)
    }
    placed = [(role, kind) for role, kind in positions(roles) if kind in by_type]

    def raw_words(field: Mapping[str, object], kind: str) -> set[str]:
        own = (_words(field.get("name")) | _words(field.get("label"))) - _words(kind)
        return own - _CURRENCY_WORDS

    def words(field: Mapping[str, object], kind: str) -> set[str]:
        return {SYNONYMS.get(word, word) for word in raw_words(field, kind)}

    def shown(left: Mapping, left_kind: str, right: Mapping, right_kind: str,
              shared: Iterable[str]) -> list[str]:
        """Each shared word as the two names spell it: 'amount', or 'total/amount'."""
        sides = (raw_words(left, left_kind), raw_words(right, right_kind))
        out = []
        for word in shared:
            spellings = sorted({
                next((raw for raw in side if SYNONYMS.get(raw, raw) == word), word)
                for side in sides
            })
            out.append("/".join(spellings))
        return out

    found: list[tuple[int, int, dict]] = []
    for left_index, (left_role, left_type) in enumerate(placed):
        for right_role, right_type in placed[left_index + 1:]:
            lefts = [field for field in by_type[left_type] if _eligible(field)]
            rights = [field for field in by_type[right_type] if _eligible(field)]
            scores: dict[tuple[str, str], tuple[int, str, list[str]]] = {}
            for left in lefts:
                for right in rights:
                    value_type = str(left.get("value_type") or "")
                    if not _compatible(value_type, str(right.get("value_type") or "")):
                        continue
                    left_name = str(left.get("name") or "")
                    right_name = str(right.get("name") or "")
                    if left_name == right_name:
                        scores[(left_name, right_name)] = (100, "same_name", [])
                        continue
                    if value_type in NAME_ONLY_VALUE_TYPES:
                        continue
                    shared = sorted(words(left, left_type) & words(right, right_type))
                    if shared:
                        scores[(left_name, right_name)] = (
                            len(shared),
                            "shared_word",
                            shown(left, left_type, right, right_type, shared),
                        )
            best_left: dict[str, int] = {}
            best_right: dict[str, int] = {}
            for (left_name, right_name), (score, _, _) in scores.items():
                best_left[left_name] = max(best_left.get(left_name, 0), score)
                best_right[right_name] = max(best_right.get(right_name, 0), score)
            types = {str(field.get("name")): str(field.get("value_type") or "") for field in lefts}
            for (left_name, right_name), (score, basis, shared) in scores.items():
                if score < best_left[left_name] and score < best_right[right_name]:
                    continue
                found.append((
                    -score,
                    len(found),
                    {
                        "id": _rule_id(left_role, left_name, right_role, right_name),
                        "left": {"role": left_role, "field": left_name},
                        "right": {"role": right_role, "field": right_name},
                        "value_type": types.get(left_name, ""),
                        "basis": basis,
                        "words": shared,
                    },
                ))
    found.sort(key=lambda item: (item[0], item[1]))
    pairs = [item[2] for item in found[:MAX_CANDIDATES]]
    return {"pairs": pairs, "omitted": max(0, len(found) - MAX_CANDIDATES)}


def unpaired_fields(
    schemas: Iterable[Mapping[str, object]],
    roles: Sequence[Mapping[str, object]],
    pairs: Iterable[Mapping[str, object]],
) -> list[dict]:
    """Amount, number and date fields lacking a counterpart on some document.

    The fields a name match cannot reach: a deal's ``principal`` and its
    confirmation's ``amount`` share no word and are the same value. Listing
    them turns "write this cycle's rules" into a question per field — does
    this state the same thing as a field on another document? — which is the
    question a name match leaves open.

    Per document, not per field. A purchase order's total that paired with the
    requisition's estimate was once left off this list, though nothing paired
    it with the invoice — and total against invoice is the comparison a
    three-way match is. ``no_pair_with`` names every other role carrying a
    field of the same value type that no candidate pairs this one with.
    """

    by_type = {
        str(item.get("document_type") or ""): [
            field for field in item.get("fields") or [] if isinstance(field, Mapping)
        ]
        for item in schemas
        if isinstance(item, Mapping)
    }
    paired_with: dict[tuple[str, str], set[str]] = {}
    for pair in pairs:
        left = pair.get("left") or {}
        right = pair.get("right") or {}
        for side, other in ((left, right), (right, left)):
            key = (str(side.get("role") or ""), str(side.get("field") or ""))
            paired_with.setdefault(key, set()).add(str(other.get("role") or ""))
    placed = positions(roles)
    carried = {
        role: {
            str(field.get("value_type") or "")
            for field in by_type.get(document_type) or []
            if _eligible(field)
        }
        for role, document_type in placed
    }
    listed: list[dict] = []
    for role, document_type in placed:
        for field in by_type.get(document_type) or []:
            name = str(field.get("name") or "")
            value_type = str(field.get("value_type") or "")
            if not _eligible(field) or value_type not in UNPAIRED_VALUE_TYPES:
                continue
            reached = paired_with.get((role, name), set())
            missing = [
                other
                for other, _ in placed
                if other != role and other not in reached and value_type in carried[other]
            ]
            if not missing:
                continue
            listed.append({
                "role": role,
                "field": name,
                "value_type": value_type,
                "label": str(field.get("label") or ""),
                "no_pair_with": missing,
            })
    return listed


def as_assertion(
    pair: Mapping[str, object], schemas: Iterable[Mapping[str, object]],
    roles: Sequence[Mapping[str, object]],
) -> dict:
    """The assertion a kept pair becomes, worded from the schemas' own labels.

    The rationale says the pair came from the schemas and why, because that is
    what an auditor approving the rules needs to know about a rule no model
    wrote: it was proposed by name and survived review, not argued for.
    """

    types = {str(role.get("name") or ""): str(role.get("document_type") or "") for role in roles}
    labels = {
        (str(item.get("document_type") or ""), str(field.get("name") or "")): str(
            field.get("label") or field.get("name") or ""
        )
        for item in schemas
        if isinstance(item, Mapping)
        for field in item.get("fields") or []
        if isinstance(field, Mapping)
    }

    def label_of(side: Mapping[str, object]) -> str:
        role = str(side.get("role") or "")
        field = str(side.get("field") or "")
        label = labels.get((types.get(role, ""), field)) or field.replace("_", " ")
        return label[:1].lower() + label[1:]

    def described(side: Mapping[str, object]) -> str:
        return f"the {label_of(side)} on the {str(side.get('role') or '').replace('_', ' ')}"

    left_side = pair.get("left") or {}
    right_side = pair.get("right") or {}
    left = described(left_side)
    right = described(right_side)
    if pair.get("value_type") in NAME_ONLY_VALUE_TYPES:
        requirement = f"{left[:1].upper()}{left[1:]} is the same date as {right}."
    else:
        requirement = f"{left[:1].upper()}{left[1:]} agrees with {right}."
    def spelled(word: str) -> str:
        if "/" not in word:
            return f"the word '{word}'"
        first, second = word.split("/", 1)
        return f"the synonyms '{first}' and '{second}'"

    basis = (
        "the same field name"
        if pair.get("basis") == "same_name"
        else ", ".join(spelled(str(word)) for word in pair.get("words") or [])
    )
    heading = label_of(left_side)
    return {
        "id": str(pair.get("id") or ""),
        "label": (
            f"{heading[:1].upper()}{heading[1:]} agrees between "
            f"{str(left_side.get('role') or '').replace('_', ' ')} and "
            f"{str(right_side.get('role') or '').replace('_', ' ')}"
        ),
        "left": dict(left_side),
        "right": dict(right_side),
        "requirement": requirement,
        "rationale": (
            f"Proposed from the document schemas, where the two fields share "
            f"{basis}, and kept on review: linked records should state the "
            "same value in both."
        ),
        "proposed_by": "schema_names",
    }


def signature(assertion: Mapping[str, object]) -> frozenset:
    """The unordered pair of operands an assertion reads."""

    return frozenset(
        (str((assertion.get(side) or {}).get("role") or ""),
         str((assertion.get(side) or {}).get("field") or ""))
        for side in ("left", "right")
        if isinstance(assertion.get(side), Mapping)
    )
