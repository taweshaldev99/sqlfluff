"""Tests for RF01's dbt context using already-rendered SQL."""

import pytest

from sqlfluff.core import FluffConfig, Linter


@pytest.fixture
def rf01_linter() -> Linter:
    """Build a strict BigQuery linter without requiring a dbt connection."""
    config = FluffConfig(
        configs={
            "core": {
                "dialect": "bigquery",
                "templater": "raw",
                "rules": "RF01",
                "use_rust_parser": False,
                "use_rust_rules": False,
            },
            "rules": {"references.from": {"force_enable": True}},
        }
    )
    return Linter(config=config)


@pytest.mark.parametrize(
    "templater,reference,expected_violation",
    [
        pytest.param("dbt", "_dbt_max_partition", False, id="dbt-variable"),
        pytest.param("dbt", "_DBT_MAX_PARTITION", False, id="uppercase-variable"),
        pytest.param("dbt", "`_dbt_max_partition`", False, id="quoted-variable"),
        pytest.param("raw", "_dbt_max_partition", True, id="raw-context"),
        pytest.param("jinja", "_dbt_max_partition", True, id="jinja-context"),
        pytest.param("dbt", "_dbt_other_variable", True, id="other-variable"),
        pytest.param("dbt", "missing_table.id", True, id="missing-table"),
        pytest.param(
            "dbt", "missing_table._dbt_max_partition", True, id="missing-qualifier"
        ),
        pytest.param("dbt", "_dbt_max_partition.id", True, id="variable-as-qualifier"),
        pytest.param("dbt", "t._dbt_max_partition", False, id="existing-qualifier"),
    ],
)
def test__rules__std_RF01_dbt_max_partition(
    rf01_linter: Linter,
    templater: str,
    reference: str,
    expected_violation: bool,
) -> None:
    """Recognize the dbt variable without hiding other reference errors."""
    parsed = rf01_linter.parse_string(
        f"SELECT t.id FROM some_table AS t WHERE t.ingestion_date >= DATE({reference});"
    )
    assert not parsed.violations
    assert parsed.tree is not None

    # Test rule evaluation on already-rendered SQL, without running dbt.
    parsed.config.set_value(["templater"], templater)
    violations = rf01_linter.lint(parsed.tree, config=parsed.config)

    expected = (
        [
            (
                "RF01",
                f"Reference {reference!r} refers to table/view "
                "not found in the FROM clause or found in ancestor statement.",
            )
        ]
        if expected_violation
        else []
    )
    assert [(v.rule_code(), v.description) for v in violations] == expected


@pytest.mark.parametrize(
    "sql,expected_reference",
    [
        pytest.param(
            "SELECT t.id FROM some_table AS t WHERE EXISTS "
            "(SELECT s.id FROM second_table AS s "
            "WHERE s.ingestion_date >= DATE(_dbt_max_partition));",
            None,
            id="subquery-variable",
        ),
        pytest.param(
            "WITH recent AS (SELECT t.id FROM some_table AS t "
            "WHERE t.ingestion_date >= DATE(_dbt_max_partition)) "
            "SELECT recent.id FROM recent;",
            None,
            id="cte-variable",
        ),
        pytest.param(
            "SELECT t.id FROM some_table AS t WHERE EXISTS "
            "(SELECT missing_table.id FROM second_table AS s "
            "WHERE s.ingestion_date >= DATE(_dbt_max_partition));",
            "missing_table.id",
            id="subquery-missing-reference",
        ),
    ],
)
def test__rules__std_RF01_dbt_max_partition_nested(
    rf01_linter: Linter, sql: str, expected_reference: str | None
) -> None:
    """Apply the dbt context inside child queries while checking other names."""
    parsed = rf01_linter.parse_string(sql)
    assert not parsed.violations
    assert parsed.tree is not None

    parsed.config.set_value(["templater"], "dbt")
    violations = rf01_linter.lint(parsed.tree, config=parsed.config)

    expected = (
        [
            (
                "RF01",
                f"Reference {expected_reference!r} refers to table/view "
                "not found in the FROM clause or found in ancestor statement.",
            )
        ]
        if expected_reference is not None
        else []
    )
    assert [(v.rule_code(), v.description) for v in violations] == expected
