from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
PROJECT_ROOT = REPO_ROOT if (REPO_ROOT / "ui").exists() else SERVICE_DIR
UI_ROOT = PROJECT_ROOT / "ui"
ORDER_VUI_DIR = UI_ROOT / "order_vui"
TABLE_GUI_DIR = UI_ROOT / "table_gui"
