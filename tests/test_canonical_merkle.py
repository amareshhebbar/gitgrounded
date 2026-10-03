from hypothesis import given
from hypothesis import strategies as st

from gitgrounded.canonical import canonical_bytes, content_hash
from gitgrounded.evidence.merkle import inclusion_proof, merkle_root, verify_inclusion

json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(-(10**9), 10**9)
    | st.floats(allow_nan=False, allow_infinity=False, width=32)
    | st.text(max_size=20),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4),
    max_leaves=12,
)


@given(json_values)
def test_canonical_is_stable(value):
    assert canonical_bytes(value) == canonical_bytes(value)


def test_key_order_does_not_matter():
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})


def test_float_normalization():
    assert canonical_bytes(1.0) == canonical_bytes(1)
    assert canonical_bytes(0.1 + 0.2) == canonical_bytes(0.3)


@given(st.lists(st.binary(max_size=40), min_size=1, max_size=40), st.data())
def test_inclusion_proofs(leaves, data):
    root = merkle_root(leaves)
    i = data.draw(st.integers(0, len(leaves) - 1))
    assert verify_inclusion(leaves[i], inclusion_proof(leaves, i), root)


def test_root_changes_on_edit():
    leaves = [b"a", b"b", b"c"]
    assert merkle_root(leaves) != merkle_root([b"a", b"x", b"c"])
    assert merkle_root(leaves) != merkle_root([b"a", b"b"])
