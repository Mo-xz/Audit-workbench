"""Field pairs proposed from the schemas, and the review that keeps or declines them.

The pairs are a floor. A proposal turn asked to write a cycle's rules from the
requirements' words never compared a goods receipt's quantity with its order's
— the one comparison that finds goods billed and paid for but not delivered —
because "matched to the order and the receipt" names no quantity. Which field of
one document is which field of another is a property of the schemas, so it is
proposed from them; a pair the review does not decline is a rule.
"""

from __future__ import annotations

import json

import pytest

from app import cycle_field_pairs, cycle_rulesets, document_schemas, workspaces
from app.agent.workers.model import WorkerResponseValidationError
from app.agent.workers.tests import _linkage_response_schema, validate_linkage_proposal


def _field(name, value_type="text", role="attribute", label=None):
    return {"name": name, "role": role, "value_type": value_type,
            "label": label or name.replace("_", " ").capitalize()}


ORDER = {"document_type": "purchase_order", "fields": [
    _field("order_reference", "identifier", "identifier"),
    _field("vendor_name", role="party"),
    _field("vendor_address", role="party"),
    _field("quantity", "number"),
    _field("po_total", "amount", label="PO total (PKR)"),
    _field("po_date", "date"),
    _field("approved_by", role="control"),
]}
RECEIPT = {"document_type": "goods_receipt", "fields": [
    _field("grn_number", "identifier", "identifier"),
    _field("purchase_order_number", "identifier", "identifier"),
    _field("vendor_name", role="party"),
    _field("quantity_received", "number"),
    _field("receipt_date", "date"),
    _field("received_by", role="control"),
]}
INVOICE = {"document_type": "vendor_invoice", "fields": [
    _field("invoice_number", "identifier", "identifier"),
    _field("purchase_reference", "identifier", "identifier"),
    _field("invoice_amount", "amount", label="Invoice amount"),
    _field("invoice_currency"),
    _field("due_date", "date"),
]}
REQUISITION = {"document_type": "purchase_requisition", "fields": [
    _field("requisition_id", "identifier", "identifier"),
    _field("proposed_vendor", role="party"),
    _field("currency"),
]}
SCHEMAS = [REQUISITION, ORDER, RECEIPT, INVOICE]
ROLES = [
    {"name": "requisition", "document_type": "purchase_requisition"},
    {"name": "financial_approval", "document_type": "purchase_requisition"},
    {"name": "order", "document_type": "purchase_order"},
    {"name": "receipt", "document_type": "goods_receipt"},
    {"name": "invoice", "document_type": "vendor_invoice"},
]


def _pairs(schemas=SCHEMAS, roles=ROLES):
    return {
        (pair["left"]["role"], pair["left"]["field"],
         pair["right"]["role"], pair["right"]["field"]): pair
        for pair in cycle_field_pairs.candidates(schemas, roles)["pairs"]
    }


# ------------------------------------------------------------------ the floor
def test_a_shared_word_pairs_receipt_quantity_with_order_quantity():
    pair = _pairs()[("order", "quantity", "receipt", "quantity_received")]
    assert pair["basis"] == "shared_word"
    assert pair["words"] == ["quantity"]


def test_the_same_name_on_two_documents_is_a_pair():
    assert _pairs()[("order", "vendor_name", "receipt", "vendor_name")]["basis"] == "same_name"


def test_identifiers_and_controls_are_never_paired():
    """References are joins, and a control records who did one step."""

    fields = {
        side["field"]
        for pair in _pairs().values()
        for side in (pair["left"], pair["right"])
    }
    assert not fields & {"order_reference", "grn_number", "approved_by", "received_by"}


def test_dates_pair_only_under_one_name():
    """A due date and a payment date share a word and must differ."""

    assert not any(
        pair["value_type"] == "date" and pair["basis"] != "same_name"
        for pair in _pairs().values()
    )


def test_a_field_s_own_document_type_does_not_make_a_match():
    """'invoice' in an invoice's invoice_currency names the document."""

    assert ("financial_approval", "currency", "invoice", "invoice_currency") in _pairs()
    assert not any(
        pair["words"] == ["invoice"] for pair in _pairs().values()
    )


def test_another_type_s_word_still_matches():
    """'vendor' names the invoice type, and still pairs a requisition's vendor."""

    assert ("financial_approval", "proposed_vendor", "order", "vendor_name") in _pairs()


def test_ties_are_all_kept():
    """Keeping one of a tie chose bank_name over counterparty for a
    confirmation's counterparty_bank, hiding a deal booked to the wrong bank."""

    deal = {"document_type": "deal_ticket", "fields": [
        _field("deal_reference", "identifier", "identifier"),
        _field("counterparty", role="party"),
        _field("bank_name", role="party"),
    ]}
    confirmation = {"document_type": "fx_contract", "fields": [
        _field("our_reference", "identifier", "identifier"),
        _field("counterparty_bank", role="party"),
    ]}
    pairs = _pairs([deal, confirmation], [
        {"name": "deal", "document_type": "deal_ticket"},
        {"name": "confirmation", "document_type": "fx_contract"},
    ])
    assert ("deal", "counterparty", "confirmation", "counterparty_bank") in pairs
    assert ("deal", "bank_name", "confirmation", "counterparty_bank") in pairs


def test_roles_sharing_a_type_pair_from_the_last_of_them():
    """A requisition raised and then approved is one record; the approved state
    is what a later document must preserve, and pairing the two positions with
    each other would compare a field with itself."""

    roles = {pair["left"]["role"] for pair in _pairs().values()} | {
        pair["right"]["role"] for pair in _pairs().values()
    }
    assert "financial_approval" in roles
    assert "requisition" not in roles


def test_a_total_and_an_amount_pair_as_synonyms():
    """A PO total and an invoice amount are one value under two words."""

    pair = _pairs()[("order", "po_total", "invoice", "invoice_amount")]
    assert pair["words"] == ["amount/total"]
    assertion = cycle_field_pairs.as_assertion(pair, SCHEMAS, ROLES)
    assert "the synonyms 'amount' and 'total'" in assertion["rationale"]


def test_an_invoice_supplier_pairs_with_an_order_vendor():
    invoice = {**INVOICE, "fields": [*INVOICE["fields"], _field("supplier_name", role="party")]}
    pairs = _pairs([REQUISITION, ORDER, RECEIPT, invoice])
    assert ("order", "vendor_name", "invoice", "supplier_name") in pairs


def test_a_currency_code_in_a_label_is_not_a_shared_word():
    requisition = {**REQUISITION, "fields": [
        *REQUISITION["fields"],
        _field("estimated_unit_cost", "amount", label="Estimated unit cost (PKR)"),
    ]}
    pairs = _pairs([requisition, ORDER, RECEIPT, INVOICE])
    # "PKR" is all the unit cost and the PO total have in common.
    assert ("financial_approval", "estimated_unit_cost", "order", "po_total") not in pairs


def _unpaired(schemas=SCHEMAS, roles=ROLES):
    candidates = cycle_field_pairs.candidates(schemas, roles)["pairs"]
    return {
        (item["role"], item["field"]): item["no_pair_with"]
        for item in cycle_field_pairs.unpaired_fields(schemas, roles, candidates)
    }


def test_a_field_paired_with_one_document_is_still_listed_for_another():
    """Paired with the requisition is not paired with the invoice."""

    requisition = {**REQUISITION, "fields": [
        *REQUISITION["fields"], _field("approved_budget", "amount", label="Approved budget"),
    ]}
    order = {**ORDER, "fields": [
        *(field for field in ORDER["fields"] if field["name"] != "po_total"),
        _field("order_budget", "amount", label="Order budget"),
    ]}
    unpaired = _unpaired([requisition, order, RECEIPT, INVOICE])
    assert unpaired[("order", "order_budget")] == ["invoice"]


def test_a_field_paired_wherever_its_type_appears_is_not_listed():
    unpaired = _unpaired()
    assert ("order", "quantity") not in unpaired
    assert ("order", "po_total") not in unpaired
    # Dates pair only under one name, so each is asked about.
    assert unpaired[("order", "po_date")] == ["receipt", "invoice"]


def test_a_large_vocabulary_is_capped_and_says_how_much_it_left_out(monkeypatch):
    monkeypatch.setattr(cycle_field_pairs, "MAX_CANDIDATES", 2)
    result = cycle_field_pairs.candidates(SCHEMAS, ROLES)
    assert len(result["pairs"]) == 2
    assert result["omitted"] > 0
    # The strongest first: a same-name pair is never the one left out of a
    # shared-word one.
    assert result["pairs"][0]["basis"] == "same_name"


def test_a_kept_pair_is_worded_from_the_schema_labels():
    pair = _pairs()[("order", "quantity", "receipt", "quantity_received")]
    assertion = cycle_field_pairs.as_assertion(pair, SCHEMAS, ROLES)
    assert assertion["id"] == pair["id"]
    assert assertion["requirement"] == (
        "The quantity on the order agrees with the quantity received on the receipt."
    )
    assert assertion["proposed_by"] == "schema_names"
    assert cycle_rulesets.valid_rule_id(assertion["id"])


# -------------------------------------------------------------- the review
class _Item:
    def __init__(self, source_id, content):
        self.source_id, self.content = source_id, content


class _Context:
    def __init__(self, items):
        self.items = items


class _Request:
    def __init__(self, requirements=None):
        steps = [
            {"name": "Purchase order", "roles": [ROLES[2]], "populations": [], "themes": []},
            {"name": "Goods receipt", "roles": [ROLES[3]], "populations": [], "themes": []},
            {"name": "Invoice", "roles": [ROLES[4]],
             "populations": [{"table": "invoices", "anchor": True}], "themes": []},
        ]
        self.unit_input = {"cycle": {"name": "P2P", "steps": steps}}
        items = [_Item("cycle_schemas", {"schemas": [ORDER, RECEIPT, INVOICE]})]
        if requirements is not None:
            items.append(_Item("cycle_requirements", {"cycle_requirements": requirements}))
        self.context = _Context(items)


QUANTITY = "pair_order_quantity_receipt_quantity_received"
VENDOR_ADDRESS_TO_NAME = "pair_order_vendor_address_receipt_vendor_name"


def _response(**overrides):
    response = {
        "cycle_label": "P2P",
        "roles": [
            {"name": "order", "document_type": "purchase_order"},
            {"name": "receipt", "document_type": "goods_receipt"},
            {"name": "invoice", "document_type": "vendor_invoice"},
        ],
        "anchor": {"role": "invoice", "field": "invoice_number", "column": "INVOICE_ID"},
        "join_keys": [
            {"id": "order_to_receipt",
             "left": {"role": "order", "field": "order_reference"},
             "right": {"role": "receipt", "field": "purchase_order_number"},
             "rationale": "A receipt records its order."},
            {"id": "order_to_invoice",
             "left": {"role": "order", "field": "order_reference"},
             "right": {"role": "invoice", "field": "purchase_reference"},
             "rationale": "An invoice cites its order."},
        ],
        "assertions": [],
    }
    response.update(overrides)
    return _linkage_response_schema(json.dumps(response))


def _ids(proposal):
    return [item["id"] for item in proposal["assertions"]]


def test_a_review_that_says_nothing_keeps_every_pair():
    """Its worst case is the floor: the receipt quantity is compared anyway."""

    proposal = validate_linkage_proposal(_response(), _Request())
    assert QUANTITY in _ids(proposal)
    assert proposal["declined_pairs"] == []


def test_a_declined_pair_leaves_the_rules_and_is_recorded_with_its_reason():
    proposal = validate_linkage_proposal(
        _response(declined_pairs=[{
            "id": VENDOR_ADDRESS_TO_NAME,
            "reason": "An address is not a name.",
        }]),
        _Request(),
    )
    assert VENDOR_ADDRESS_TO_NAME not in _ids(proposal)
    (declined,) = proposal["declined_pairs"]
    assert declined["reason"] == "An address is not a name."
    assert declined["left"] == {"role": "order", "field": "vendor_address"}


def test_a_decline_without_a_reason_is_refused():
    with pytest.raises(WorkerResponseValidationError, match="with no reason"):
        validate_linkage_proposal(
            _response(declined_pairs=[{"id": QUANTITY, "reason": ""}]), _Request()
        )


def test_a_decline_naming_no_supplied_pair_is_refused():
    with pytest.raises(WorkerResponseValidationError, match="not one of the field pairs"):
        validate_linkage_proposal(
            _response(declined_pairs=[{"id": "pair_invented", "reason": "x"}]),
            _Request(),
        )


def test_an_authored_rule_over_a_pair_s_fields_replaces_it():
    """The pair kept in the turn's own words, and coverage follows it."""

    authored = {
        "id": "received_quantity_agrees", "label": "Received in full",
        "left": {"role": "receipt", "field": "quantity_received"},
        "right": {"role": "order", "field": "quantity"},
        "requirement": "Every unit ordered was received.",
        "rationale": "Billing in full needs receipt in full.",
    }
    requirement = {"rcm_id": "RCM-1", "control_attribute": "match",
                   "requirement": "The invoice is matched to the order and receipt."}
    proposal = validate_linkage_proposal(
        _response(
            assertions=[authored],
            coverage=[{"rcm_id": "RCM-1", "control_attribute": "match",
                       "reads": ["order", "receipt"], "assertion_ids": [QUANTITY]}],
        ),
        _Request(requirements=[requirement]),
    )
    assert "received_quantity_agrees" in _ids(proposal)
    assert QUANTITY not in _ids(proposal)
    assert proposal["coverage"][0]["assertion_ids"] == ["received_quantity_agrees"]


def test_a_pair_both_declined_and_written_is_refused():
    authored = {
        "id": "received_quantity_agrees", "label": "Received in full",
        "left": {"role": "receipt", "field": "quantity_received"},
        "right": {"role": "order", "field": "quantity"},
        "requirement": "Every unit ordered was received.", "rationale": "x",
    }
    with pytest.raises(WorkerResponseValidationError, match="Keep one"):
        validate_linkage_proposal(
            _response(assertions=[authored],
                      declined_pairs=[{"id": QUANTITY, "reason": "Not comparable."}]),
            _Request(),
        )


def test_a_rule_restating_a_join_key_is_refused():
    """The join made the two references equal; the rule cannot fail."""

    authored = {
        "id": "receipt_cites_order", "label": "Receipt cites order",
        "left": {"role": "receipt", "field": "purchase_order_number"},
        "right": {"role": "order", "field": "order_reference"},
        "requirement": "The receipt names the order.", "rationale": "x",
    }
    with pytest.raises(WorkerResponseValidationError, match="cannot fail"):
        validate_linkage_proposal(_response(assertions=[authored]), _Request())


def test_coverage_citing_a_declined_pair_is_refused():
    requirement = {"rcm_id": "RCM-1", "control_attribute": "match",
                   "requirement": "The receipt agrees with the order."}
    with pytest.raises(WorkerResponseValidationError, match="which this proposal declines"):
        validate_linkage_proposal(
            _response(
                declined_pairs=[{"id": QUANTITY, "reason": "Not comparable."}],
                coverage=[{"rcm_id": "RCM-1", "control_attribute": "match",
                           "reads": ["order", "receipt"], "assertion_ids": [QUANTITY]}],
            ),
            _Request(requirements=[requirement]),
        )


def test_a_kept_pair_answers_the_reach_check():
    """Citing the floor's pair reads the receipt, which is what the match needs."""

    requirement = {"rcm_id": "RCM-1", "control_attribute": "match",
                   "requirement": "The invoice is matched to the order and receipt."}
    proposal = validate_linkage_proposal(
        _response(coverage=[{
            "rcm_id": "RCM-1", "control_attribute": "match",
            "reads": ["order", "receipt"], "assertion_ids": [QUANTITY],
        }]),
        _Request(requirements=[requirement]),
    )
    assert proposal["coverage"][0]["assertion_ids"] == [QUANTITY]


def test_pairs_on_a_role_the_proposal_cannot_reach_are_dropped():
    """A role listed unreachable is out of the rules, and so are its pairs."""

    response = _response()
    response["roles"] = [role for role in response["roles"] if role["name"] != "receipt"]
    response["join_keys"] = [
        key for key in response["join_keys"] if key["id"] != "order_to_receipt"
    ]
    response["unreachable"] = [{"role": "receipt", "reason": "No identifier."}]
    response["assertions"] = [{
        "id": "invoice_within_order", "label": "Billed as ordered",
        "left": {"role": "invoice", "field": "invoice_amount"},
        "right": {"role": "order", "field": "po_total"},
        "requirement": "The invoice bills no more than the order.", "rationale": "x",
    }]
    proposal = validate_linkage_proposal(response, _Request())
    assert not any("receipt" in assertion_id for assertion_id in _ids(proposal))


def test_a_pair_written_out_under_its_own_id_is_the_pair_kept():
    """Measured live: the review restates kept pairs under the ids it was given."""

    authored = {
        "id": QUANTITY, "label": "Received in full",
        "left": {"role": "order", "field": "quantity"},
        "right": {"role": "receipt", "field": "quantity_received"},
        "requirement": "Every unit ordered was received.", "rationale": "x",
    }
    proposal = validate_linkage_proposal(_response(assertions=[authored]), _Request())
    (kept,) = [item for item in proposal["assertions"] if item["id"] == QUANTITY]
    assert kept["requirement"] == "Every unit ordered was received."


def test_a_pair_s_id_over_other_fields_is_refused():
    authored = {
        "id": QUANTITY, "label": "x",
        "left": {"role": "order", "field": "po_total"},
        "right": {"role": "invoice", "field": "invoice_amount"},
        "requirement": "x", "rationale": "x",
    }
    with pytest.raises(WorkerResponseValidationError, match="compares different fields"):
        validate_linkage_proposal(_response(assertions=[authored]), _Request())


def test_declining_a_pair_on_a_role_it_cannot_reach_is_accepted():
    """Measured live: a statement with no identifier was declined, correctly."""

    response = _response()
    response["roles"] = [role for role in response["roles"] if role["name"] != "receipt"]
    response["join_keys"] = [
        key for key in response["join_keys"] if key["id"] != "order_to_receipt"
    ]
    response["unreachable"] = [{"role": "receipt", "reason": "No identifier."}]
    response["assertions"] = [{
        "id": "invoice_within_order", "label": "Billed as ordered",
        "left": {"role": "invoice", "field": "invoice_amount"},
        "right": {"role": "order", "field": "po_total"},
        "requirement": "x", "rationale": "x",
    }]
    response["declined_pairs"] = [{"id": QUANTITY, "reason": "The receipt is unreachable."}]
    proposal = validate_linkage_proposal(response, _Request())
    assert proposal["declined_pairs"] == []


# --------------------------------------------------------------- the store
def test_declines_are_stored_beside_the_rules_and_outside_their_hash():
    workspace = workspaces.create_workspace("Field pair store")
    for schema in (ORDER, INVOICE):
        document_schemas.save_schema(workspace, schema["document_type"], schema["fields"])
    workspace = workspaces.load_workspace(workspace.id)
    payload = {
        "cycle_label": "P2P",
        "roles": [{"name": "order", "document_type": "purchase_order"},
                  {"name": "invoice", "document_type": "vendor_invoice"}],
        "anchor": {"table": "invoices", "column": "INVOICE_ID",
                   "role": "invoice", "field": "invoice_number"},
        "join_keys": [{"id": "order_to_invoice",
                       "left": {"role": "order", "field": "order_reference"},
                       "right": {"role": "invoice", "field": "purchase_reference"}}],
        "assertions": [{"id": "pair_x", "label": "x", "requirement": "x",
                        "left": {"role": "order", "field": "po_total"},
                        "right": {"role": "invoice", "field": "invoice_amount"},
                        "proposed_by": "schema_names"}],
    }
    plain = cycle_rulesets.validate(workspace, payload)
    declined = cycle_rulesets.validate(workspace, {**payload, "declined_pairs": [{
        "id": "pair_y", "left": {"role": "order", "field": "vendor_name"},
        "right": {"role": "invoice", "field": "invoice_currency"},
        "basis": "shared_word", "reason": "A name is not a currency.",
    }]})

    assert declined["declined_pairs"][0]["reason"] == "A name is not a currency."
    assert declined["ruleset_hash"] == plain["ruleset_hash"]
    assert declined["assertions"][0]["proposed_by"] == "schema_names"
