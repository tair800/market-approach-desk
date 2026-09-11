"""Guards that need no database, no credential and no network.

Kept out of the integration module deliberately. An ``import n8n`` inside ``src/``, a fixture naming
a real underwriter, or an integration run pointed at something that is not a throwaway database are
all things that must fail on an ordinary ``pytest`` run — not only on a machine that happens to have
PostgreSQL up.

They lived in the kill-test module first, and that was wrong twice over: the autouse async fixture
there cannot be applied to a sync test, so they surfaced as a collection error rather than running.
"""

from __future__ import annotations

import ast
import os
import pathlib


def test_the_shipped_package_does_not_import_the_baseline() -> None:
    """`src/` must never know `n8n/` exists.

    The dependency runs one way: the baseline reads the shipped domain types so both arms are
    measured identically, and the shipped service may not know the baseline is there. A guard in
    the default suite rather than behind the integration mark, because an `import n8n` inside
    `src/` would otherwise sit there with lint and types green.
    """

    package = pathlib.Path(__file__).resolve().parents[1] / "src" / "market_approach_desk"
    inspected = 0
    for path in package.rglob("*.py"):
        inspected += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                assert module.split(".")[0] != "n8n", (
                    f"{path.name} imports {module}: the shipped service must not know the n8n "
                    "baseline exists, or the comparison is no longer between two implementations"
                )
    assert inspected >= 8, "the scan is not seeing the package"


def test_the_fixtures_name_no_real_party() -> None:
    """Every carrier, underwriter and address in the fixtures is invented.

    Checked rather than asserted in a docstring: a public repository that shipped a real
    underwriter's address would be a disclosure, and the person who added the fixture would not be
    the person who noticed.
    """
    from market_approach_desk.demo import seed as seeder

    source = pathlib.Path(seeder.__file__).read_text(encoding="utf-8")
    assert "@example.invalid" in source, "fixture addresses must use the reserved invalid TLD"
    for real in ("@gmail", "@outlook", "@lloyds", '.com"', ".co.uk"):
        assert real not in source, f"fixtures contain something that looks real: {real!r}"


def test_the_environment_is_a_disposable_database() -> None:
    """The race test truncates tables. Refuse to do that to anything but a throwaway database."""
    dsn = os.environ.get("MAD_POSTGRES_DSN", "")
    assert "localhost" in dsn or "127.0.0.1" in dsn or dsn == "", (
        "the integration suite resets every table; it may only run against a local database"
    )
