from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.lte_channel_config import write_default_lte_channel_excel


def main() -> None:
    output_path = PROJECT_ROOT / "configs" / "lte_channel_config.xlsx"
    write_default_lte_channel_excel(output_path)
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
