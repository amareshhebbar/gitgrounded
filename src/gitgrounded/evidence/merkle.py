import hashlib

LEAF = b"\x00"
NODE = b"\x01"


def leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(LEAF + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(NODE + left + right).digest()


def merkle_root(leaves: list[bytes]) -> str:
    if not leaves:
        return hashlib.sha256(b"").hexdigest()
    level = [leaf_hash(x) for x in leaves]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(node_hash(level[i], level[i + 1]))
            else:
                nxt.append(level[i])
        level = nxt
    return level[0].hex()


def inclusion_proof(leaves: list[bytes], index: int) -> list[dict[str, str]]:
    level = [leaf_hash(x) for x in leaves]
    proof = []
    idx = index
    while len(level) > 1:
        sibling = idx ^ 1
        if sibling < len(level):
            proof.append({"side": "left" if sibling < idx else "right", "hash": level[sibling].hex()})
        nxt = []
        for i in range(0, len(level), 2):
            nxt.append(node_hash(level[i], level[i + 1]) if i + 1 < len(level) else level[i])
        level = nxt
        idx //= 2
    return proof


def verify_inclusion(leaf: bytes, proof: list[dict[str, str]], root: str) -> bool:
    h = leaf_hash(leaf)
    for step in proof:
        sib = bytes.fromhex(step["hash"])
        h = node_hash(sib, h) if step["side"] == "left" else node_hash(h, sib)
    return h.hex() == root
