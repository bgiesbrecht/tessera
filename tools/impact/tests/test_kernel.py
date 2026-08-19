"""Kernel unit tests (scoping doc §4).

These pin the lattice relations: the only things the tool asserts as PROVEN.
They are deliberately explicit about the honest negatives (flat-axis
non-subsumption; undeclared classes; opaque selectors), because those are the
guarantees that keep the tool on the correct side of the ADR-001 line.
"""

from __future__ import annotations

from tools.impact import kernel
from tools.impact.kernel import Polarity
from tools.impact.model import Condition, Selector


# -- §4.2 #2 scope-IRI containment ------------------------------------------


def test_scope_contains_prefix():
    assert kernel.scope_contains("catalog:acme", "table:acme.tpch.orders")
    assert kernel.scope_contains("schema:acme.tpch", "table:acme.tpch.orders")
    assert kernel.scope_contains("table:acme.tpch.orders", "table:acme.tpch.orders")


def test_scope_does_not_contain_upward():
    assert not kernel.scope_contains("table:acme.tpch.orders", "catalog:acme")
    assert not kernel.scope_contains("schema:acme.sales", "table:acme.tpch.orders")


# -- §4.2 #4 attribute-axis subsumption (ontology-grounded) -----------------


def test_hierarchical_axis_subsumes_declared_subclass():
    assert kernel.attribute_value_subsumes("sensitivity", "PII", "PHI")
    assert kernel.attribute_value_subsumes("sensitivity", "PersonalData", "PII")
    assert kernel.attribute_value_subsumes("sensitivity", "PII", "PII")  # reflexive


def test_hierarchical_axis_does_not_subsume_undeclared_value():
    # PIIClerk is an adopter example value, not declared in v0's ontology.
    # The tool must not invent a subsumption it cannot prove.
    assert not kernel.attribute_value_subsumes("sensitivity", "PII", "PIIClerk")


def test_flat_axis_only_equality():
    assert kernel.attribute_value_subsumes("regulatoryRegime", "GDPR", "GDPR")
    assert not kernel.attribute_value_subsumes("regulatoryRegime", "GDPR", "HIPAA")


# -- §4.2 #3 condition value-set containment --------------------------------


def _cond(op, col, values):
    return Condition(op=op, operands=(col,), values=tuple(values))


def test_value_superset_same_column():
    outer = _cond("in", "column:t.c", ["1", "2", "3"])
    inner = _cond("in", "column:t.c", ["1"])
    assert kernel.condition_value_superset(outer, inner)
    assert not kernel.condition_value_superset(inner, outer)


def test_value_superset_different_column_not_comparable():
    a = _cond("in", "column:t.a", ["1"])
    b = _cond("in", "column:t.b", ["1"])
    assert not kernel.condition_value_superset(a, b)


def test_none_condition_is_unconditional_superset():
    inner = _cond("in", "column:t.c", ["1"])
    assert kernel.condition_value_superset(None, inner)
    assert not kernel.condition_value_superset(inner, None)


def test_opaque_operator_not_comparable():
    a = Condition(op="exists-in-dataset", operands=(), values=())
    assert not kernel.condition_comparable(a)


# -- §4.3 effect polarity ----------------------------------------------------


def test_effect_polarity():
    assert kernel.effect_polarity("allow") == Polarity.EXPOSE
    assert kernel.effect_polarity("keep-matching-rows") == Polarity.EXPOSE
    assert kernel.effect_polarity("deny") == Polarity.RESTRICT
    assert kernel.effect_polarity("drop-matching-rows") == Polarity.RESTRICT
    assert kernel.effect_polarity("transform") == Polarity.PARTIAL_RESTRICT
    assert kernel.effect_polarity("bogus") == Polarity.UNKNOWN


# -- §4.1 / §4.4 selector equality, subsumption, opacity --------------------


def test_identity_selector_equality_and_subsumption():
    a = Selector.from_dict({"selector": "byIdentity", "resource": "group:x"})
    b = Selector.from_dict({"selector": "byIdentity", "resource": "group:x"})
    c = Selector.from_dict({"selector": "byIdentity", "resource": "group:y"})
    assert kernel.selectors_equal(a, b)
    assert kernel.selector_subsumes(a, b)
    assert not kernel.selector_subsumes(a, c)


def test_scope_selector_subsumption_with_attributes():
    outer = Selector.from_dict({
        "selector": "byScope", "scope": "catalog:acme",
        "matching": {"attributes": {"sensitivity": "PII"}},
    })
    inner = Selector.from_dict({
        "selector": "byScope", "scope": "table:acme.tpch.orders",
        "matching": {"attributes": {"sensitivity": "PHI"}},
    })
    # catalog ⊇ table AND PII ⊇ PHI -> outer subsumes inner.
    assert kernel.selector_subsumes(outer, inner)
    # reverse does not hold.
    assert not kernel.selector_subsumes(inner, outer)


def test_bydataset_selector_is_opaque():
    sel = Selector.from_dict({
        "selector": "byDataset",
        "dataset": {"type": "PrincipalSetFromTable", "table": "acme.acl"},
    })
    assert kernel.selector_opaque(sel)
    # opaque selectors are never subsumed (would require reading the table).
    other = Selector.from_dict({"selector": "byIdentity", "resource": "group:x"})
    assert not kernel.selector_subsumes(sel, other)
    assert not kernel.selector_subsumes(other, sel)
