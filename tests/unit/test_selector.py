from app.config.models import KeyConfig
from app.router.selector import select_keys


def _keys() -> list[KeyConfig]:
    return [
        KeyConfig(id="k1", key="a", priority=10, weight=1),
        KeyConfig(id="k2", key="b", priority=20, weight=1),
        KeyConfig(id="k3", key="c", priority=5, weight=1),
    ]


def test_strict_priority_orders_descending() -> None:
    keys = _keys()
    ordered = select_keys("strict_priority", keys)
    assert [k.id for k in ordered] == ["k2", "k1", "k3"]


def test_least_errors_prefers_fewer_errors() -> None:
    keys = _keys()
    runtime = {
        "k1": {"consecutive_errors": 3},
        "k2": {"consecutive_errors": 1},
        "k3": {"consecutive_errors": 0},
    }
    ordered = select_keys("least_errors", keys, runtime)
    assert [k.id for k in ordered] == ["k3", "k2", "k1"]
