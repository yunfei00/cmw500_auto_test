from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ScpiMeasureConfig:
    query: str
    parser: str = "first_float"
    fallback_simulation: bool = True


@dataclass
class ScpiWaitConfig:
    query: str
    parser: str = "contains"
    expected: str = ""
    interval_sec: float = 1.0
    timeout_sec: float = 30.0
    fallback_success: bool = False


@dataclass
class LteScpiTemplate:
    setup: list[str] = field(default_factory=list)
    cell_on: list[str] = field(default_factory=list)
    wait_attach: ScpiWaitConfig | None = None
    before_measure: list[str] = field(default_factory=list)
    set_rx_level: list[str] = field(default_factory=list)
    measure_bler: ScpiMeasureConfig = field(default_factory=lambda: ScpiMeasureConfig(query=""))
    after_measure: list[str] = field(default_factory=list)
    cell_off: list[str] = field(default_factory=list)
    cleanup: list[str] = field(default_factory=list)


class ScpiTemplateManager:
    def __init__(self) -> None:
        self.lte_template: LteScpiTemplate | None = None
        self.raw_data: dict[str, Any] = {}
        self.last_parse_error = ""

    def load_file(self, file_path: str) -> None:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        elif suffix in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError as exc:
                raise RuntimeError("缺少 PyYAML，请先安装 pyyaml") from exc
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            raise ValueError("SCPI 模板文件仅支持 .yaml、.yml、.json")

        if not isinstance(data, dict):
            raise ValueError("SCPI 模板文件根节点必须是对象")
        self.raw_data = data
        self.lte_template = self._parse_lte_template(data.get("lte"))

    def has_template(self) -> bool:
        return self.lte_template is not None

    def get_lte_template(self) -> LteScpiTemplate | None:
        return self.lte_template

    def render_command(self, command: str, context: dict) -> str:
        full_context = dict(context)
        if "band_number" not in full_context and "band" in full_context:
            full_context["band_number"] = str(full_context["band"]).lstrip("Bb")
        try:
            return command.format_map(full_context)
        except KeyError as exc:
            missing_name = str(exc).strip("'")
            raise ValueError(f"SCPI 模板变量缺失：{missing_name}，原始命令：{command}") from exc

    def parse_measure_response(self, response: str, parser: str) -> float:
        parser = parser.strip()
        if parser == "first_float":
            return self._float_at(response, 0, parser)
        if parser == "second_float":
            return self._float_at(response, 1, parser)
        if parser.startswith("csv_index:"):
            index_text = parser.split(":", 1)[1]
            try:
                index = int(index_text)
                field = response.split(",")[index].strip()
                return float(field)
            except (IndexError, ValueError) as exc:
                raise ValueError(f"测量响应解析失败，parser={parser}，response={response}") from exc
        raise ValueError(f"不支持的测量响应解析器：{parser}，response={response}")

    def parse_wait_response(self, response: str, parser: str, expected: str) -> bool:
        self.last_parse_error = ""
        parser = parser.strip()
        try:
            if parser == "contains":
                return expected in response
            if parser == "equals":
                return response.strip() == expected
            if parser.startswith("first_float_ge:"):
                threshold = float(parser.split(":", 1)[1])
                return self._float_at(response, 0, parser) >= threshold
            if parser.startswith("first_float_le:"):
                threshold = float(parser.split(":", 1)[1])
                return self._float_at(response, 0, parser) <= threshold
            if parser == "regex":
                return re.search(expected, response) is not None
            self.last_parse_error = f"不支持的等待响应解析器：parser={parser}，response={response}"
            return False
        except Exception as exc:
            self.last_parse_error = f"等待响应解析失败，parser={parser}，response={response}，error={exc}"
            return False

    def _parse_lte_template(self, lte_data: Any) -> LteScpiTemplate | None:
        if lte_data is None:
            return None
        if not isinstance(lte_data, dict):
            raise ValueError("lte 模板必须是对象")

        measure_data = lte_data.get("measure_bler")
        if not isinstance(measure_data, dict) or not measure_data.get("query"):
            raise ValueError("lte.measure_bler.query 不能为空")

        return LteScpiTemplate(
            setup=self._as_command_list(lte_data.get("setup", []), "lte.setup"),
            cell_on=self._as_command_list(lte_data.get("cell_on", []), "lte.cell_on"),
            wait_attach=self._parse_wait_config(lte_data.get("wait_attach")),
            before_measure=self._as_command_list(
                lte_data.get("before_measure", []),
                "lte.before_measure",
            ),
            set_rx_level=self._as_command_list(lte_data.get("set_rx_level", []), "lte.set_rx_level"),
            measure_bler=ScpiMeasureConfig(
                query=str(measure_data["query"]),
                parser=str(measure_data.get("parser", "first_float")),
                fallback_simulation=bool(measure_data.get("fallback_simulation", True)),
            ),
            after_measure=self._as_command_list(
                lte_data.get("after_measure", []),
                "lte.after_measure",
            ),
            cell_off=self._as_command_list(lte_data.get("cell_off", []), "lte.cell_off"),
            cleanup=self._as_command_list(lte_data.get("cleanup", []), "lte.cleanup"),
        )

    def _parse_wait_config(self, wait_data: Any) -> ScpiWaitConfig | None:
        if wait_data is None:
            return None
        if not isinstance(wait_data, dict):
            raise ValueError("lte.wait_attach 必须是对象")
        if not wait_data.get("query"):
            raise ValueError("lte.wait_attach.query 不能为空")
        return ScpiWaitConfig(
            query=str(wait_data["query"]),
            parser=str(wait_data.get("parser", "contains")),
            expected=str(wait_data.get("expected", "")),
            interval_sec=float(wait_data.get("interval_sec", 1.0)),
            timeout_sec=float(wait_data.get("timeout_sec", 30.0)),
            fallback_success=bool(wait_data.get("fallback_success", False)),
        )

    def _as_command_list(self, value: Any, path: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{path} 必须是命令列表")
        return [str(item) for item in value]

    def _float_at(self, response: str, index: int, parser: str) -> float:
        matches = re.findall(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", response)
        try:
            return float(matches[index])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"测量响应解析失败，parser={parser}，response={response}") from exc
