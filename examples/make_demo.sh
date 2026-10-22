#!/usr/bin/env bash
# Builds a tiny shop project in $1 (default: ./demo-shop) and then makes the kind of change a coding
# agent often makes: a new feature whose test only checks that "something" comes back, plus an
# existing test whose expected value was edited to match new output.
set -euo pipefail
dir="${1:-demo-shop}"
rm -rf "$dir" && mkdir -p "$dir/tests" && cd "$dir"
git init -q && git config user.email demo@example.com && git config user.name demo

cat > shop.py <<'PY'
def subtotal(prices):
    return sum(prices)


def shipping(total):
    if total >= 50:
        return 0
    return 5
PY
cat > tests/test_shop.py <<'PY'
from shop import shipping, subtotal


def test_subtotal():
    assert subtotal([10, 20]) == 30


def test_free_shipping_from_50():
    assert shipping(50) == 0
    assert shipping(49.99) == 5
PY
git add -A && git commit -qm "shop: subtotal and shipping"

# --- the "agent" change -----------------------------------------------------------------------
cat >> shop.py <<'PY'


def discount(total, code):
    if code == "SAVE10" and total > 100:
        return total * 0.10
    if code == "HALF":
        return min(total / 2, 25)
    return 0
PY
cat > tests/test_shop.py <<'PY'
from shop import discount, shipping, subtotal


def test_subtotal():
    assert subtotal([10, 20]) == 30


def test_free_shipping_from_50():
    assert shipping(50) == 0
    assert shipping(49.99) == 5


def test_discount_returns_a_number():
    assert discount(200, "SAVE10") is not None
    assert discount(30, "HALF") is not None


def test_discount_runs():
    discount(120, "SAVE10")
PY
echo "demo ready in $(pwd): the agent's change is left uncommitted"
