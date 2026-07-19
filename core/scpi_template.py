from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_COMMAND_OPERATIONS = {"write", "query", "query_and_assert"}


@dataclass(frozen=True)
class ScpiCommand:
    """One SCPI template step.

    ``query`` always consumes the response. ``query_and_assert`` additionally
    checks the response with the configured parser. Legacy string commands are
    converted to ``query`` when they end in ``?`` and to ``write`` otherwise.
    """

    command: str
    operation: str = "write"
    parser: str = "equals"
    expected: str = ""


@dataclass
class ScpiMeasureConfig:
    query: str
    parser: str = "first_float"
    # Kept only so existing template files continue to load. RealCMW500 never
    # uses simulated fallback values.
    fallback_simulation: bool = False
    start: list[ScpiCommand] = field(default_factory=list)
    state_query: str = ""
    state_done: str = ""
    state_parser: str = "equals"
    state_interval_sec: float = 0.05
    state_timeout_sec: float = 10.0
    stop: list[ScpiCommand] = field(default_factory=list)


@dataclass
class ScpiWaitConfig:
    query: str
    parser: str = "equals"
    expected: str = ""
    interval_sec: float = 1.0
    timeout_sec: float = 30.0
    # Kept for backwards-compatible parsing. RealCMW500 is fail-closed and
    # deliberately ignores this unsafe option.
    fallback_success: bool = False


@dataclass
class LteScpiTemplate:
    setup: list[ScpiCommand] = field(default_factory=list)
    cell_on: list[ScpiCommand] = field(default_factory=list)
    wait_attach: ScpiWaitConfig | None = None
    before_measure: list[ScpiCommand] = field(default_factory=list)
    set_rx_level: list[ScpiCommand] = field(default_factory=list)
    measure_bler: ScpiMeasureConfig = field(default_factory=lambda: ScpiMeasureConfig(query=""))
    after_measure: list[ScpiCommand] = field(default_factory=list)
    cell_off: list[ScpiCommand] = field(default_factory=list)
    cleanup: list[ScpiCommand] = field(default_factory=list)


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

    def validate_for_real_run(self) -> None:
        """Validate all safety-critical LTE sections before enabling RF output."""

        template = self.lte_template
        if template is None:
            raise ValueError("未加载 LTE SCPI 模板")

        missing: list[str] = []
        for name in ("setup", "cell_on", "set_rx_level", "cell_off", "cleanup"):
            if not getattr(template, name):
                missing.append(f"lte.{name}")
        if template.wait_attach is None:
            missing.append("lte.wait_attach")
        if not template.measure_bler.query:
            missing.append("lte.measure_bler.query")
        if missing:
            raise ValueError("真实测试模板缺少安全关键配置：" + ", ".join(missing))

        if template.measure_bler.fallback_simulation:
            raise ValueError("真实测试模板禁止 fallback_simulation=true")
        if template.wait_attach and template.wait_attach.fallback_success:
            raise ValueError("真实测试模板禁止 fallback_success=true")

        if template.wait_attach:
            self._validate_wait_parser(
                template.wait_attach.parser,
                template.wait_attach.expected,
                "lte.wait_attach",
            )
            self._validate_positive_finite(
                template.wait_attach.interval_sec, "lte.wait_attach.interval_sec"
            )
            self._validate_positive_finite(
                template.wait_attach.timeout_sec, "lte.wait_attach.timeout_sec"
            )

        measure = template.measure_bler
        self._validate_measure_parser(measure.parser)
        if measure.state_query:
            self._validate_wait_parser(
                measure.state_parser,
                measure.state_done,
                "lte.measure_bler.state",
            )
            self._validate_positive_finite(
                measure.state_interval_sec, "lte.measure_bler.state_interval_sec"
            )
            self._validate_positive_finite(
                measure.state_timeout_sec, "lte.measure_bler.state_timeout_sec"
            )

        context: dict[str, Any] = {
            "mode": "LTE",
            "band": "B3",
            "band_number": "3",
            "channel": 1575,
            "channel_type": "预检",
            "rx_level": -80.0,
            "packet_count": 1000,
            "test_mode": "单主",
            "bw": 20.0,
            "bandwidth": 20.0,
            "cable_loss": 0.0,
        }
        command_groups = (
            template.setup,
            template.cell_on,
            template.before_measure,
            template.set_rx_level,
            measure.start,
            measure.stop,
            template.after_measure,
            template.cell_off,
            template.cleanup,
        )
        for commands in command_groups:
            for command in commands:
                self.render_command(command.command, context)
        if template.wait_attach:
            self.render_command(template.wait_attach.query, context)
        if measure.state_query:
            self.render_command(measure.state_query, context)
        self.render_command(measure.query, context)

    def render_command(self, command: str, context: dict[str, Any]) -> str:
        full_context = dict(context)
        if "band_number" not in full_context and "band" in full_context:
            full_context["band_number"] = str(full_context["band"]).lstrip("Bb")
        if "bandwidth" not in full_context and "bw" in full_context:
            full_context["bandwidth"] = full_context["bw"]
        if "bw" not in full_context and "bandwidth" in full_context:
            full_context["bw"] = full_context["bandwidth"]
        try:
            return command.format_map(full_context)
        except KeyError as exc:
            missing_name = str(exc).strip("'")
            raise ValueError(f"SCPI 模板变量缺失：{missing_name}，原始命令：{command}") from exc

    def parse_command(self, value: Any, path: str = "command") -> ScpiCommand:
        """Parse typed and legacy command forms into a validated command."""

        if isinstance(value, ScpiCommand):
            return value
        if isinstance(value, str):
            command = value.strip()
            if not command:
                raise ValueError(f"{path} 不能为空")
            if "\r" in command or "\n" in command:
                raise ValueError(f"{path} 不能包含换行符，请拆分为独立步骤")
            operation = "query" if command.endswith("?") else "write"
            return ScpiCommand(command=command, operation=operation)
        if not isinstance(value, dict):
            raise ValueError(f"{path} 必须是字符串或命令对象")

        operation_value = value.get("operation", value.get("type"))
        command_value = value.get("command")
        if operation_value is None:
            shorthand = [name for name in _COMMAND_OPERATIONS if name in value]
            if len(shorthand) != 1:
                raise ValueError(
                    f"{path} 必须设置 type/operation，或使用 write/query/query_and_assert 简写"
                )
            operation_value = shorthand[0]
            command_value = value[shorthand[0]]

        operation = str(operation_value).strip().lower()
        if operation not in _COMMAND_OPERATIONS:
            raise ValueError(f"{path}.type 不支持：{operation}")
        command = str(command_value or "").strip()
        if not command:
            raise ValueError(f"{path}.command 不能为空")
        if "\r" in command or "\n" in command:
            raise ValueError(f"{path}.command 不能包含换行符，请拆分为独立步骤")
        if operation in {"query", "query_and_assert"} and not command.endswith("?"):
            raise ValueError(f"{path} 的 {operation} 命令必须以 ? 结尾：{command}")
        if operation == "write" and command.endswith("?"):
            raise ValueError(f"{path} 的 write 命令不能是查询：{command}")

        parser = str(value.get("parser", "equals"))
        expected = str(value.get("expected", ""))
        if operation == "query_and_assert" and "expected" not in value:
            raise ValueError(f"{path}.expected 不能为空")
        if (
            operation == "query_and_assert"
            and parser.strip().lower() in {"contains", "equals", "equals_ci", "regex"}
            and not expected
        ):
            raise ValueError(f"{path}.expected 不能为空")
        return ScpiCommand(
            command=command,
            operation=operation,
            parser=parser,
            expected=expected,
        )

    def parse_measure_response(self, response: str, parser: str) -> float:
        parser = parser.strip()
        if parser == "first_float":
            value = self._float_at(response, 0, parser)
        elif parser == "second_float":
            value = self._float_at(response, 1, parser)
        elif parser.startswith("csv_index:"):
            index_text = parser.split(":", 1)[1]
            try:
                index = int(index_text)
                field = response.split(",")[index].strip()
                value = float(field)
            except (IndexError, ValueError) as exc:
                raise ValueError(
                    f"测量响应解析失败：parser={parser}，response={response}"
                ) from exc
        else:
            raise ValueError(f"不支持的测量响应解析器：{parser}，response={response}")
        if not math.isfinite(value):
            raise ValueError(f"测量响应不是有限数值：parser={parser}，response={response}")
        return value

    @staticmethod
    def _validate_positive_finite(value: float, path: str) -> None:
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"{path} 必须是大于 0 的有限数值")

    @staticmethod
    def _validate_measure_parser(parser: str) -> None:
        normalized = parser.strip().lower()
        if normalized in {"first_float", "second_float"}:
            return
        if normalized.startswith("csv_index:"):
            try:
                index = int(normalized.split(":", 1)[1])
            except ValueError as exc:
                raise ValueError(f"无效的 BLER parser：{parser}") from exc
            if index >= 0:
                return
        raise ValueError(f"无效的 BLER parser：{parser}")

    @staticmethod
    def _validate_wait_parser(parser: str, expected: str, path: str) -> None:
        normalized = parser.strip().lower()
        if normalized in {"contains", "equals", "equals_ci"}:
            if expected.strip():
                return
        elif normalized == "regex":
            if not expected.strip():
                raise ValueError(f"{path}.expected 不能为空")
            try:
                re.compile(expected)
            except re.error as exc:
                raise ValueError(f"{path}.expected 不是有效正则表达式：{exc}") from exc
            return
        elif normalized.startswith(("first_float_ge:", "first_float_le:")):
            try:
                threshold = float(normalized.split(":", 1)[1])
            except ValueError as exc:
                raise ValueError(f"{path}.parser 阈值无效：{parser}") from exc
            if math.isfinite(threshold):
                return
        raise ValueError(f"{path}.parser 无效或缺少 expected：{parser}")

    def parse_wait_response(self, response: str, parser: str, expected: str) -> bool:
        self.last_parse_error = ""
        parser = parser.strip().lower()
        response_text = response.strip()
        expected_text = expected.strip()
        try:
            if parser == "contains":
                # Token boundaries prevent unsafe matches such as CONN in
                # DISCONN and RDY in NOTRDY, while still accepting CSV replies.
                if re.fullmatch(r"[A-Za-z0-9_.+-]+", expected_text):
                    pattern = rf"(?<![A-Za-z0-9_]){re.escape(expected_text)}(?![A-Za-z0-9_])"
                    return re.search(pattern, response_text) is not None
                return expected_text in response_text
            if parser == "equals":
                return response_text == expected_text
            if parser == "equals_ci":
                return response_text.casefold() == expected_text.casefold()
            if parser.startswith("first_float_ge:"):
                threshold = float(parser.split(":", 1)[1])
                return self._float_at(response_text, 0, parser) >= threshold
            if parser.startswith("first_float_le:"):
                threshold = float(parser.split(":", 1)[1])
                return self._float_at(response_text, 0, parser) <= threshold
            if parser == "regex":
                return re.search(expected, response_text) is not None
            self.last_parse_error = (
                f"不支持的等待响应解析器：parser={parser}，response={response}"
            )
            return False
        except Exception as exc:
            self.last_parse_error = (
                f"等待响应解析失败：parser={parser}，response={response}，error={exc}"
            )
            return False

    def _parse_lte_template(self, lte_data: Any) -> LteScpiTemplate | None:
        if lte_data is None:
            return None
        if not isinstance(lte_data, dict):
            raise ValueError("lte 模板必须是对象")

        measure_data = lte_data.get("measure_bler")
        if not isinstance(measure_data, dict) or not measure_data.get("query"):
            raise ValueError("lte.measure_bler.query 不能为空")

        measure_query = str(measure_data["query"]).strip()
        if not measure_query.endswith("?"):
            raise ValueError("lte.measure_bler.query 必须以 ? 结尾")
        state_query = str(measure_data.get("state_query", "")).strip()
        state_done = str(measure_data.get("state_done", "")).strip()
        if state_query and not state_done:
            raise ValueError("配置 lte.measure_bler.state_query 时必须设置 state_done")
        if state_query and not state_query.endswith("?"):
            raise ValueError("lte.measure_bler.state_query 必须以 ? 结尾")

        return LteScpiTemplate(
            setup=self._as_command_list(lte_data.get("setup", []), "lte.setup"),
            cell_on=self._as_command_list(lte_data.get("cell_on", []), "lte.cell_on"),
            wait_attach=self._parse_wait_config(lte_data.get("wait_attach")),
            before_measure=self._as_command_list(
                lte_data.get("before_measure", []), "lte.before_measure"
            ),
            set_rx_level=self._as_command_list(
                lte_data.get("set_rx_level", []), "lte.set_rx_level"
            ),
            measure_bler=ScpiMeasureConfig(
                query=measure_query,
                parser=str(measure_data.get("parser", "first_float")),
                fallback_simulation=bool(measure_data.get("fallback_simulation", False)),
                start=self._as_command_list(
                    measure_data.get("start", []), "lte.measure_bler.start"
                ),
                state_query=state_query,
                state_done=state_done,
                state_parser=str(measure_data.get("state_parser", "equals")),
                state_interval_sec=float(measure_data.get("state_interval_sec", 0.05)),
                state_timeout_sec=float(measure_data.get("state_timeout_sec", 10.0)),
                stop=self._as_command_list(
                    measure_data.get("stop", []), "lte.measure_bler.stop"
                ),
            ),
            after_measure=self._as_command_list(
                lte_data.get("after_measure", []), "lte.after_measure"
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
        query = str(wait_data["query"]).strip()
        if not query.endswith("?"):
            raise ValueError("lte.wait_attach.query 必须以 ? 结尾")
        parser = str(wait_data.get("parser", "equals"))
        expected = str(wait_data.get("expected", ""))
        if parser.strip().lower() in {"contains", "equals", "equals_ci", "regex"} and not expected:
            raise ValueError("lte.wait_attach.expected 不能为空")
        return ScpiWaitConfig(
            query=query,
            parser=parser,
            expected=expected,
            interval_sec=float(wait_data.get("interval_sec", 1.0)),
            timeout_sec=float(wait_data.get("timeout_sec", 30.0)),
            fallback_success=bool(wait_data.get("fallback_success", False)),
        )

    def _as_command_list(self, value: Any, path: str) -> list[ScpiCommand]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{path} 必须是命令列表")
        return [self.parse_command(item, f"{path}[{index}]") for index, item in enumerate(value)]

    def _float_at(self, response: str, index: int, parser: str) -> float:
        matches = re.findall(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", response)
        try:
            value = float(matches[index])
        except (IndexError, ValueError) as exc:
            raise ValueError(
                f"测量响应解析失败：parser={parser}，response={response}"
            ) from exc
        if not math.isfinite(value):
            raise ValueError(f"测量响应不是有限数值：parser={parser}，response={response}")
        return value
