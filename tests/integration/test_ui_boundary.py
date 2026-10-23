"""The screen only renders and calls the API: nothing in ui/ may import kestrel (plan, Structure Decision)."""
import ast
from pathlib import Path

UI_DIR = Path(__file__).resolve().parents[2] / "ui"


def test_ui_scripts_exist():
    assert (UI_DIR / "app.py").is_file()
    assert (UI_DIR / "api_client.py").is_file()


def test_ui_never_imports_kestrel():
    offenders = []
    for path in sorted(UI_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            offenders += [f"{path.name}: {name}" for name in names if name == "kestrel" or name.startswith("kestrel.")]
    assert offenders == []
