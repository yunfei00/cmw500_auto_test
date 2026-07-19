from __future__ import annotations

import json

import pytest

from core.scpi_template import ScpiTemplateManager


def test_typed_and_legacy_commands_are_parsed_safely() -> None:
    manager = ScpiTemplateManager()

    legacy_write = manager.parse_command("INST LTE")
    legacy_query = manager.parse_command("SYST:ERR?")
    typed_query = manager.parse_command(
        {"type": "query", "command": "CONF:LTE:BAND?"}
    )
    asserted = manager.parse_command(
        {
            "query_and_assert": "SYST:ERR?",
            "parser": "regex",
            "expected": r"^0(?:,|$)",
        }
    )

    assert legacy_write.operation == "write"
    assert legacy_query.operation == "query"
    assert typed_query.operation == "query"
    assert asserted.operation == "query_and_assert"
    with pytest.raises(ValueError, match="write 命令不能是查询"):
        manager.parse_command({"type": "write", "command": "SYST:ERR?"})
    with pytest.raises(ValueError, match="不能包含换行符"):
        manager.parse_command({"type": "write", "command": "CELL OFF\nCELL ON"})


def test_contains_parser_uses_token_boundaries() -> None:
    manager = ScpiTemplateManager()

    assert manager.parse_wait_response("RRC,CONN", "contains", "CONN")
    assert not manager.parse_wait_response("DISCONN", "contains", "CONN")
    assert manager.parse_wait_response("STATUS,RDY", "contains", "RDY")
    assert not manager.parse_wait_response("NOTRDY", "contains", "RDY")


def test_context_supports_bandwidth_aliases() -> None:
    manager = ScpiTemplateManager()

    assert manager.render_command("BW {bandwidth}", {"bw": 10}) == "BW 10"
    assert manager.render_command("BW {bw}", {"bandwidth": 20}) == "BW 20"


def test_template_fallback_defaults_to_false(tmp_path) -> None:
    path = tmp_path / "template.json"
    path.write_text(
        json.dumps(
            {
                "lte": {
                    "setup": ["INST LTE", "CONF?"],
                    "measure_bler": {"query": "FETC:BLER?"},
                }
            }
        ),
        encoding="utf-8",
    )

    manager = ScpiTemplateManager()
    manager.load_file(str(path))
    template = manager.get_lte_template()

    assert template is not None
    assert template.measure_bler.fallback_simulation is False
    assert [step.operation for step in template.setup] == ["write", "query"]


def test_real_run_preflight_requires_safety_sections(tmp_path) -> None:
    path = tmp_path / "incomplete.json"
    path.write_text(
        json.dumps({"lte": {"setup": ["INST LTE"], "measure_bler": {"query": "BLER?"}}}),
        encoding="utf-8",
    )
    manager = ScpiTemplateManager()
    manager.load_file(str(path))

    with pytest.raises(ValueError, match="cell_on"):
        manager.validate_for_real_run()


def test_recommended_template_passes_real_run_preflight() -> None:
    manager = ScpiTemplateManager()
    manager.load_file("config/cmw500_lte_scpi_template.cmw500_recommended.yaml")

    manager.validate_for_real_run()


def test_real_run_preflight_rejects_fallback_flags(tmp_path) -> None:
    path = tmp_path / "unsafe.json"
    path.write_text(
        json.dumps(
            {
                "lte": {
                    "setup": ["INST LTE"],
                    "cell_on": ["CELL ON"],
                    "wait_attach": {
                        "query": "RRC?",
                        "parser": "equals",
                        "expected": "CONN",
                        "fallback_success": True,
                    },
                    "set_rx_level": ["RX {rx_level}"],
                    "measure_bler": {"query": "BLER?"},
                    "cell_off": ["CELL OFF"],
                    "cleanup": ["SYST:ERR?"],
                }
            }
        ),
        encoding="utf-8",
    )
    manager = ScpiTemplateManager()
    manager.load_file(str(path))

    with pytest.raises(ValueError, match="fallback_success"):
        manager.validate_for_real_run()


@pytest.mark.parametrize("response", ["nan", "inf", "-inf"])
def test_measure_parser_rejects_non_finite_values(response: str) -> None:
    manager = ScpiTemplateManager()
    with pytest.raises(ValueError):
        manager.parse_measure_response(response, "first_float")
