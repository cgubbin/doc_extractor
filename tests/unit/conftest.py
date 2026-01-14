import pytest


@pytest.fixture
def norm_ws():
    # small helper so snippets are readable
    def _norm(s: str) -> str:
        return " ".join((s or "").split())

    return _norm
