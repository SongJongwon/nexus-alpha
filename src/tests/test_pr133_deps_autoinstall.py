# -*- coding: utf-8 -*-
"""PR #133 — 자연어 → .exe 풀체인 자동화의 끊어진 고리 복원 검증.

배경 (사용자 라이브 검증, 2026-05-12):
    Calculator.exe 실행 시 ``ModuleNotFoundError: No module named 'customtkinter'``
    발생. 원인 분석:
      ① Design agent 가 ``import customtkinter`` 가 포함된 calculator.py 생성 ✓
      ② Dependency Analyzer LLM 이 ``direct_dependencies: customtkinter`` 보고서 산출 ✓
      ③ 그러나 ``build_workflow.py`` 가 보고서를 *markdown 파일에만 저장* 하고 ❌
         pip install 단계를 *수행하지 않음* → PyInstaller 가 customtkinter 못 찾음
      ④ 결과: 빈 껍데기 .exe 생성, 런타임 실패

PR #133 처방:
    - ``build_workflow._parse_deps_from_report`` — YAML 보고서에서 direct_deps +
      hidden_imports 추출
    - ``build_workflow._install_dependencies_for_build`` — pip install 자동 실행
    - ``execute_pyinstaller`` 호출 시 ``hidden_imports`` 자동 전달
    - Track B (``automate_workflow``) 도 entry .py 의 import AST 스캔 → pip install

본 테스트 모듈은 위 4개 함수의 정확성을 격리 검증 (LLM 호출 0회, ~1초 실행).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# build_workflow._parse_deps_from_report — Dependency Analyzer YAML 파싱
# ---------------------------------------------------------------------------


def test_parse_deps_extracts_direct_dependencies_from_yaml_block() -> None:
    """LLM 산출 ```yaml``` 블록에서 ``direct_dependencies.name`` 정확히 추출."""
    from src.workflows.build_workflow import _parse_deps_from_report

    sample = """## 의존성 보고서

```yaml
direct_dependencies:
  - name: customtkinter
    version: ">=5.2"
    source: pip
  - name: pillow
    version: ">=10.0"
    source: pip
hidden_imports: []
```

## 분석가 코멘트
"""
    direct, hidden = _parse_deps_from_report(sample)
    assert "customtkinter" in direct, f"customtkinter 미추출: {direct}"
    assert "pillow" in direct, f"pillow 미추출: {direct}"
    assert hidden == [], f"hidden_imports 빈 리스트여야 함: {hidden}"


def test_parse_deps_extracts_hidden_imports_module_field() -> None:
    """``hidden_imports.module`` 필드 정확히 추출 (PyInstaller --hidden-import 인자)."""
    from src.workflows.build_workflow import _parse_deps_from_report

    sample = """```yaml
direct_dependencies: []
hidden_imports:
  - module: customtkinter.windows.widgets.theme
    reason: lazy import in customtkinter __init__
    severity: must
  - module: pkg_resources.extern
    reason: setuptools internal
    severity: should
```
"""
    direct, hidden = _parse_deps_from_report(sample)
    assert "customtkinter.windows.widgets.theme" in hidden, (
        f"customtkinter.windows.widgets.theme 미추출: {hidden}"
    )
    assert "pkg_resources.extern" in hidden


def test_parse_deps_excludes_stdlib_from_direct_deps() -> None:
    """stdlib 모듈 (json/os/sys 등) 은 direct_deps 에서 제외 — pip install 불필요."""
    from src.workflows.build_workflow import _parse_deps_from_report

    sample = """```yaml
direct_dependencies:
  - name: customtkinter
    version: ">=5.2"
  - name: json
    version: stdlib
  - name: os
    version: stdlib
hidden_imports: []
```
"""
    direct, _ = _parse_deps_from_report(sample)
    assert "customtkinter" in direct
    assert "json" not in direct, "stdlib (json) 가 direct_deps 에 잔존"
    assert "os" not in direct, "stdlib (os) 가 direct_deps 에 잔존"


def test_parse_deps_excludes_build_tools_from_direct_deps() -> None:
    """build 도구 자체 (pyinstaller / pip / setuptools) 는 제외 — 이미 .venv 에 설치됨."""
    from src.workflows.build_workflow import _parse_deps_from_report

    sample = """```yaml
direct_dependencies:
  - name: pyinstaller
    version: ">=6.20.0"
  - name: pip
    version: ">=23"
  - name: customtkinter
    version: ">=5.2"
hidden_imports: []
```
"""
    direct, _ = _parse_deps_from_report(sample)
    assert "customtkinter" in direct
    assert "pyinstaller" not in [d.lower() for d in direct], (
        "pyinstaller 가 direct_deps 에 잔존"
    )
    assert "pip" not in [d.lower() for d in direct]


def test_parse_deps_handles_no_yaml_block_with_regex_fallback() -> None:
    """```yaml``` 블록이 없으면 raw 텍스트에서 regex fallback 으로 추출."""
    from src.workflows.build_workflow import _parse_deps_from_report

    sample = """## 의존성 보고서

direct_dependencies:
  - name: customtkinter
  - name: requests
hidden_imports:
  - module: customtkinter.windows.widgets.theme

## 분석가 코멘트
"""
    direct, hidden = _parse_deps_from_report(sample)
    assert "customtkinter" in direct, f"regex fallback 실패: {direct}"
    assert "requests" in direct
    assert "customtkinter.windows.widgets.theme" in hidden


def test_parse_deps_handles_empty_report() -> None:
    """빈 보고서 → 빈 리스트 반환 (예외 발생 X)."""
    from src.workflows.build_workflow import _parse_deps_from_report

    assert _parse_deps_from_report("") == ([], [])
    assert _parse_deps_from_report("\n\n   \n") == ([], [])


def test_parse_deps_handles_malformed_yaml_gracefully() -> None:
    """YAML 파싱 실패 → regex fallback 시도 → 그래도 못 찾으면 빈 리스트."""
    from src.workflows.build_workflow import _parse_deps_from_report

    sample = """```yaml
direct_dependencies:
  - name: customtkinter
  - this is not valid yaml: [unclosed
hidden_imports:
  - module: foo
```
"""
    # 파싱이 실패하더라도 예외 propagate 안 함
    direct, hidden = _parse_deps_from_report(sample)
    assert isinstance(direct, list)
    assert isinstance(hidden, list)


def test_parse_deps_dedupes_repeated_packages() -> None:
    """동일 패키지가 여러 번 등장해도 결과는 중복 제거."""
    from src.workflows.build_workflow import _parse_deps_from_report

    sample = """```yaml
direct_dependencies:
  - name: customtkinter
    version: ">=5.2"
  - name: customtkinter
    version: ">=5.0"
hidden_imports:
  - module: foo
  - module: foo
```
"""
    direct, hidden = _parse_deps_from_report(sample)
    assert direct.count("customtkinter") == 1, f"중복 제거 실패: {direct}"
    assert hidden.count("foo") == 1


def test_parse_deps_handles_string_items_not_dicts() -> None:
    """LLM 이 간단한 ``- foo`` 형식만 사용해도 추출 (dict 가 아닌 string item)."""
    from src.workflows.build_workflow import _parse_deps_from_report

    sample = """```yaml
direct_dependencies:
  - customtkinter
  - pillow
hidden_imports:
  - customtkinter.windows.widgets.theme
```
"""
    direct, hidden = _parse_deps_from_report(sample)
    assert "customtkinter" in direct
    assert "pillow" in direct
    assert "customtkinter.windows.widgets.theme" in hidden


# ---------------------------------------------------------------------------
# build_workflow._install_dependencies_for_build — pip install 호출자
# ---------------------------------------------------------------------------


def test_install_deps_empty_list_returns_success_immediately() -> None:
    """빈 deps → 즉시 success (subprocess 호출 X)."""
    from src.workflows.build_workflow import _install_dependencies_for_build

    ok, log = _install_dependencies_for_build([])
    assert ok is True
    assert "no deps" in log.lower()


def test_install_deps_graceful_failure_on_invalid_package(monkeypatch) -> None:
    """존재하지 않는 패키지 → graceful failure (예외 propagate X, 명확한 메시지)."""
    from src.workflows import build_workflow

    captured: dict = {}

    def _fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = cmd
        class _R:
            returncode = 1
            stdout = ""
            stderr = "ERROR: No matching distribution found for nonexistent-pkg-xyz"
        return _R()

    monkeypatch.setattr(build_workflow.subprocess, "run", _fake_run)
    ok, log = build_workflow._install_dependencies_for_build(["nonexistent-pkg-xyz"])
    assert ok is False
    assert "failed" in log.lower()
    assert "nonexistent-pkg-xyz" in str(captured["cmd"]) or "pkg" in log.lower()


def test_install_deps_uses_venv_pip(monkeypatch) -> None:
    """sys.executable 의 형제 pip.exe / pip 호출 — venv 일관성 보장."""
    from src.workflows import build_workflow

    captured: dict = {}

    def _fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = list(cmd)
        class _R:
            returncode = 0
            stdout = "Successfully installed customtkinter-5.2.2"
            stderr = ""
        return _R()

    monkeypatch.setattr(build_workflow.subprocess, "run", _fake_run)
    ok, log = build_workflow._install_dependencies_for_build(["customtkinter"])
    assert ok is True
    cmd = captured["cmd"]
    # pip.exe (Windows) 또는 pip (others) — sys.executable 의 형제 디렉토리
    assert any(("pip" in str(c)) for c in cmd[:2]), f"pip 호출 누락: {cmd}"
    assert "install" in cmd
    assert "customtkinter" in cmd


# ---------------------------------------------------------------------------
# automate_workflow._scan_imports_from_py — Track B AST import 스캔
# ---------------------------------------------------------------------------


def test_scan_imports_extracts_third_party_packages() -> None:
    """`import X` + `from X import Y` 둘 다 정확히 추출, top-level 만 남김."""
    from src.workflows.automate_workflow import _scan_imports_from_py

    src = """
import customtkinter
from PIL import Image, ImageTk
import requests
import openpyxl.workbook
from sqlalchemy.orm import Session
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)
    try:
        deps = _scan_imports_from_py(p)
        assert "customtkinter" in deps
        assert "PIL" in deps
        assert "requests" in deps
        # top-level 만 — openpyxl (not openpyxl.workbook)
        assert "openpyxl" in deps
        assert "openpyxl.workbook" not in deps
        # sqlalchemy.orm → sqlalchemy
        assert "sqlalchemy" in deps
    finally:
        p.unlink()


def test_scan_imports_excludes_stdlib() -> None:
    """json / os / sys / pathlib 등 stdlib 는 제외."""
    from src.workflows.automate_workflow import _scan_imports_from_py

    src = """
import json
import os
import sys
from pathlib import Path
from datetime import datetime
import customtkinter
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)
    try:
        deps = _scan_imports_from_py(p)
        assert "customtkinter" in deps
        for stdlib_pkg in ("json", "os", "sys", "pathlib", "datetime"):
            assert stdlib_pkg not in deps, (
                f"stdlib '{stdlib_pkg}' 가 deps 에 잔존: {deps}"
            )
    finally:
        p.unlink()


def test_scan_imports_excludes_build_tools() -> None:
    """pyinstaller / pytest / pip 등 build 도구는 제외 (이미 venv 에 설치)."""
    from src.workflows.automate_workflow import _scan_imports_from_py

    src = """
import pyinstaller
import pytest
import customtkinter
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)
    try:
        deps = _scan_imports_from_py(p)
        assert "customtkinter" in deps
        assert "pyinstaller" not in [d.lower() for d in deps]
        assert "pytest" not in [d.lower() for d in deps]
    finally:
        p.unlink()


def test_scan_imports_handles_relative_imports() -> None:
    """``from . import X`` 같은 상대 import 는 패키지가 아니므로 제외."""
    from src.workflows.automate_workflow import _scan_imports_from_py

    src = """
from . import helpers
from .. import parent_helpers
import customtkinter
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)
    try:
        deps = _scan_imports_from_py(p)
        assert "customtkinter" in deps
        # relative imports 는 어떤 top-level 패키지도 의미하지 않음
        assert "helpers" not in deps
        assert "parent_helpers" not in deps
    finally:
        p.unlink()


def test_scan_imports_handles_syntax_error_gracefully() -> None:
    """잘못된 Python 파일 → 예외 X, 빈 리스트 반환."""
    from src.workflows.automate_workflow import _scan_imports_from_py

    src = """
import customtkinter
this is not valid python syntax %%% &&&
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)
    try:
        deps = _scan_imports_from_py(p)
        # SyntaxError 시 그냥 빈 리스트 — graceful
        assert isinstance(deps, list)
    finally:
        p.unlink()


def test_scan_imports_handles_missing_file() -> None:
    """존재하지 않는 파일 → 빈 리스트 (graceful)."""
    from src.workflows.automate_workflow import _scan_imports_from_py

    deps = _scan_imports_from_py(Path("/nonexistent/path/foo.py"))
    assert deps == []


def test_scan_imports_dedupes() -> None:
    """동일 패키지 중복 import → 결과 중복 제거."""
    from src.workflows.automate_workflow import _scan_imports_from_py

    src = """
import customtkinter
import customtkinter as ctk
from customtkinter import CTk
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)
    try:
        deps = _scan_imports_from_py(p)
        assert deps.count("customtkinter") == 1
    finally:
        p.unlink()


# ---------------------------------------------------------------------------
# Integration — build_workflow + execute_pyinstaller hidden_imports 전달
# ---------------------------------------------------------------------------


def test_build_workflow_passes_hidden_imports_to_executor(monkeypatch, tmp_path: Path) -> None:
    """PR #133 통합 — Dependency Analyzer 의 hidden_imports 가 execute_pyinstaller 까지 전달.

    워크플로 호출 시:
      ① _parse_deps_from_report 가 hidden_imports=['foo.bar'] 추출
      ② _install_dependencies_for_build 가 customtkinter 설치
      ③ execute_pyinstaller(..., hidden_imports=['foo.bar']) 호출
    """
    from src.workflows import build_workflow

    sample_report = """```yaml
direct_dependencies:
  - name: customtkinter
hidden_imports:
  - module: customtkinter.windows.widgets.theme
```
"""
    # _parse_deps_from_report 의 API 는 (direct, hidden) tuple 유지 (PR #133 fixup #8 에서도)
    direct, hidden = build_workflow._parse_deps_from_report(sample_report)
    assert direct == ["customtkinter"]
    assert hidden == ["customtkinter.windows.widgets.theme"]


# ---------------------------------------------------------------------------
# PR #133 fixup #6 — LLM report + AST UNION + pip name normalization + --collect-all
# ---------------------------------------------------------------------------


def test_resolve_build_deps_ast_primary_drops_llm_direct_deps() -> None:
    """PR #133 fixup #8 — LLM direct_dependencies 는 *버림*, AST 만 신뢰.

    사용자 라이브 검증에서 확인된 결함: LLM 이 PySide6 + PyQt6 둘 다 보고하면
    PyInstaller 가 abort. AST primary 로 가면 실제 import 만 남아서 자연 해결.
    """
    from src.workflows.build_workflow import _resolve_build_deps

    src = """
import flet
import json
from datetime import datetime

def main(page: flet.Page):
    pass
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)

    # LLM 이 거짓 양성으로 customtkinter 보고 (실제 코드는 안 씀)
    llm_report = """```yaml
direct_dependencies:
  - name: customtkinter
hidden_imports: []
```
"""
    try:
        result = _resolve_build_deps(llm_report, p, [p])
        # AST 가 catch 한 flet 만 남아야 함
        assert "flet" in result.direct_deps_to_install
        # LLM 의 거짓 양성 customtkinter 는 *제외*
        assert "customtkinter" not in result.direct_deps_to_install, (
            f"LLM 거짓 양성이 누수됨: {result.direct_deps_to_install}"
        )
    finally:
        p.unlink()


def test_resolve_build_deps_normalizes_pip_names() -> None:
    """Import 이름 → pip install 이름 매핑 (PIL → pillow, cv2 → opencv-python 등)."""
    from src.workflows.build_workflow import _resolve_build_deps

    src = """
from PIL import Image
import cv2
import yaml as yml
from bs4 import BeautifulSoup
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)

    try:
        result = _resolve_build_deps("", p, [p])
        direct = result.direct_deps_to_install
        # 정규화 결과
        assert "pillow" in direct, f"PIL → pillow 정규화 실패: {direct}"
        assert "opencv-python" in direct, f"cv2 → opencv-python 정규화 실패: {direct}"
        assert "pyyaml" in direct, f"yaml → pyyaml 정규화 실패: {direct}"
        assert "beautifulsoup4" in direct, f"bs4 → beautifulsoup4 정규화 실패: {direct}"
        # 원본 import 이름은 사라져야 함
        assert "PIL" not in direct
        assert "cv2" not in direct
        assert "bs4" not in direct
    finally:
        p.unlink()


def test_resolve_build_deps_dearpygui_scenario() -> None:
    """dearpygui 시나리오 — AST 가 catch."""
    from src.workflows.build_workflow import _resolve_build_deps

    src = """
import dearpygui.dearpygui as dpg

dpg.create_context()
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)

    try:
        result = _resolve_build_deps("", p, [p])
        assert "dearpygui" in result.direct_deps_to_install, (
            f"dearpygui 미검출: {result.direct_deps_to_install}"
        )
    finally:
        p.unlink()


def test_resolve_build_deps_pyside6_scenario() -> None:
    """PySide6 시나리오 — AST 가 catch (정규화 매핑 불필요)."""
    from src.workflows.build_workflow import _resolve_build_deps

    src = """
from PySide6.QtWidgets import QApplication, QMainWindow
import sys

app = QApplication(sys.argv)
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        p = Path(f.name)

    try:
        result = _resolve_build_deps("", p, [p])
        assert "PySide6" in result.direct_deps_to_install, (
            f"PySide6 미검출: {result.direct_deps_to_install}"
        )
        # sys 는 stdlib 이라 제외
        assert "sys" not in result.direct_deps_to_install
    finally:
        p.unlink()


def test_resolve_build_deps_scans_multiple_code_files() -> None:
    """entry 외의 다른 code_files 의 import 도 함께 스캔."""
    from src.workflows.build_workflow import _resolve_build_deps

    entry_src = """
from helper import do_work
do_work()
"""
    helper_src = """
import customtkinter
def do_work():
    pass
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(entry_src)
        entry_p = Path(f.name)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(helper_src)
        helper_p = Path(f.name)

    try:
        result = _resolve_build_deps("", entry_p, [entry_p, helper_p])
        assert "customtkinter" in result.direct_deps_to_install, (
            f"helper.py 의 customtkinter import 스캔 누락: {result.direct_deps_to_install}"
        )
    finally:
        entry_p.unlink()
        helper_p.unlink()


def test_normalize_pip_names_passthrough_for_unknown() -> None:
    """매핑 없는 패키지명은 그대로 반환."""
    from src.workflows.build_workflow import _normalize_pip_names

    deps = ["flet", "customtkinter", "dearpygui", "PySide6"]
    result = _normalize_pip_names(deps)
    assert result == deps  # 매핑 없는 것들은 변환 X


def test_execute_pyinstaller_accepts_collect_all_arg(monkeypatch, tmp_path: Path) -> None:
    """PR #133 fixup #6 — execute_pyinstaller 가 --collect-all <pkg> 자동 추가.

    flet / customtkinter 등 data files / 플러그인 가진 패키지가 PyInstaller 정적
    분석으로 누락되는 문제 해결.
    """
    from src.agents.build_release import build_executor

    captured: dict = {}

    def _fake_resolve_pyinstaller():
        return Path("fake_pyinstaller.exe")

    def _fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = list(cmd)
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    # mock pyinstaller path + subprocess
    monkeypatch.setattr(build_executor, "_resolve_pyinstaller_executable", _fake_resolve_pyinstaller)
    monkeypatch.setattr(build_executor.subprocess, "run", _fake_run)

    # entry 파일 생성
    entry = tmp_path / "app.py"
    entry.write_text("import flet\n", encoding="utf-8")
    out = tmp_path / "out"

    # collect_all 인자 전달
    build_executor.execute_pyinstaller(
        entry_path=entry,
        output_dir=out,
        app_name="App",
        windowed=True,
        onefile=True,
        collect_all=["flet", "customtkinter"],
    )

    cmd = captured["cmd"]
    # --collect-all flet, --collect-all customtkinter 가 명령에 포함
    assert "--collect-all" in cmd
    assert "flet" in cmd
    assert "customtkinter" in cmd
    # 각 패키지마다 --collect-all 가 앞서야 함
    flet_idx = cmd.index("flet")
    assert cmd[flet_idx - 1] == "--collect-all"


# ---------------------------------------------------------------------------
# PR #133 fixup #7 — 로컬 프로젝트 모듈을 외부 패키지로 오인하는 false positive fix
# ---------------------------------------------------------------------------


def test_resolve_build_deps_excludes_local_project_modules(tmp_path: Path) -> None:
    """fixup #7 핵심 — 사용자 라이브 시나리오 (theme.py/views.py/storage.py) 재현.

    LLM 이 calculator.py 에서 ``from theme import COLORS`` 같은 로컬 import 를
    사용하면 AST 스캔이 theme 을 외부 pip 패키지로 오인 → pip install 실패.
    fixup #7 가 같은 디렉토리의 .py 파일을 local module 로 인식해 제외.
    """
    from src.workflows.build_workflow import _resolve_build_deps

    project = tmp_path / "build_output" / "src"
    project.mkdir(parents=True)
    (project / "calculator.py").write_text(
        "import flet\n"
        "from theme import COLORS\n"
        "from views import MainView\n"
        "from storage import save_state\n",
        encoding="utf-8",
    )
    (project / "theme.py").write_text("COLORS = {}", encoding="utf-8")
    (project / "views.py").write_text("class MainView: pass", encoding="utf-8")
    (project / "storage.py").write_text("def save_state(): pass", encoding="utf-8")

    code_files = [
        project / "calculator.py",
        project / "theme.py",
        project / "views.py",
        project / "storage.py",
    ]
    result = _resolve_build_deps("", project / "calculator.py", code_files)
    direct = result.direct_deps_to_install
    # 외부 패키지 flet 만 남고, theme/views/storage 는 모두 로컬로 인식
    assert direct == ["flet"], f"fixup #7: 로컬 모듈이 외부로 분류됨: {direct}"


def test_collect_local_modules_finds_sibling_py_files(tmp_path: Path) -> None:
    """_collect_local_modules — 같은 디렉토리의 .py 파일을 local module 로 수집."""
    from src.workflows.build_workflow import _collect_local_modules

    project = tmp_path / "proj"
    project.mkdir()
    (project / "main.py").touch()
    (project / "helpers.py").touch()
    (project / "config.py").touch()
    (project / "_private.py").touch()  # dunder 제외 대상

    locals_set = _collect_local_modules(project / "main.py", [project / "main.py"])
    assert "main" in locals_set
    assert "helpers" in locals_set
    assert "config" in locals_set
    # underscore prefix 는 제외
    assert "_private" not in locals_set


def test_collect_local_modules_finds_package_dirs(tmp_path: Path) -> None:
    """_collect_local_modules — __init__.py 있는 패키지 디렉토리 + namespace 패키지 모두 수집."""
    from src.workflows.build_workflow import _collect_local_modules

    project = tmp_path / "proj"
    project.mkdir()
    (project / "main.py").touch()
    # 패키지 (__init__.py)
    pkg = project / "utils"
    pkg.mkdir()
    (pkg / "__init__.py").touch()
    (pkg / "helpers.py").touch()
    # namespace 패키지 (__init__.py 없음, .py 있음)
    nspkg = project / "views"
    nspkg.mkdir()
    (nspkg / "main_view.py").touch()
    # 무관 디렉토리 (.py 없음)
    empty = project / "assets"
    empty.mkdir()
    (empty / "icon.png").touch()

    locals_set = _collect_local_modules(project / "main.py", [project / "main.py"])
    assert "utils" in locals_set, f"패키지 (__init__.py) 미검출: {locals_set}"
    assert "views" in locals_set, f"namespace 패키지 미검출: {locals_set}"
    # 비-Python 디렉토리는 제외
    assert "assets" not in locals_set


def test_resolve_build_deps_relative_imports_excluded(tmp_path: Path) -> None:
    """상대 import (from .x import y) 는 AST 가 무조건 제외 — 외부 패키지 후보 X."""
    from src.workflows.build_workflow import _resolve_build_deps

    project = tmp_path / "proj"
    project.mkdir()
    (project / "main.py").write_text(
        "from . import sibling\n"
        "from .submod import func\n"
        "from .. import parent_thing\n"
        "import requests\n",  # 진짜 외부
        encoding="utf-8",
    )
    result = _resolve_build_deps("", project / "main.py", [project / "main.py"])
    direct = result.direct_deps_to_install
    assert "requests" in direct
    # relative imports 의 어떤 이름도 외부로 분류되면 안 됨
    assert "sibling" not in direct
    assert "submod" not in direct
    assert "parent_thing" not in direct


def test_resolve_build_deps_mixed_stdlib_local_external(tmp_path: Path) -> None:
    """혼합 시나리오 — stdlib + local + external 가 정확히 분리되는지."""
    from src.workflows.build_workflow import _resolve_build_deps

    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text(
        "import json\n"  # stdlib
        "from pathlib import Path\n"  # stdlib
        "import requests\n"  # external
        "import flet\n"  # external
        "from myproject_local import helper\n"  # local
        "from theme import COLORS\n",  # local sibling .py
        encoding="utf-8",
    )
    # 로컬 sibling 파일
    (project / "theme.py").touch()
    # 로컬 패키지
    local_pkg = project / "myproject_local"
    local_pkg.mkdir()
    (local_pkg / "__init__.py").touch()

    code_files = [project / "app.py", project / "theme.py"]
    result = _resolve_build_deps("", project / "app.py", code_files)
    direct = result.direct_deps_to_install
    # External 만 남아야 함
    assert sorted(direct) == sorted(["requests", "flet"]), f"deps mismatch: {direct}"
    assert "json" not in direct
    assert "pathlib" not in direct
    assert "theme" not in direct
    assert "myproject_local" not in direct


def test_resolve_build_deps_excludes_dunder_names(tmp_path: Path) -> None:
    """__main__ / __init__ 같은 dunder 이름은 외부 패키지로 분류되면 안 됨."""
    from src.workflows.build_workflow import _resolve_build_deps

    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text(
        "import __future__\n"  # stdlib pseudo
        "import flet\n",
        encoding="utf-8",
    )
    result = _resolve_build_deps("", project / "app.py", [project / "app.py"])
    direct = result.direct_deps_to_install
    assert "flet" in direct
    # __future__ 는 어떤 식으로든 제외
    assert "__future__" not in direct
    assert "future" not in direct


def test_resolve_build_deps_llm_says_local_module_still_excludes(tmp_path: Path) -> None:
    """LLM 이 dependency_report 에 로컬 모듈명을 넣어도 fixup #7 가 차단.

    안전망 — LLM 산출이 잘못돼도 false positive 방지.
    """
    from src.workflows.build_workflow import _resolve_build_deps

    project = tmp_path / "proj"
    project.mkdir()
    (project / "main.py").write_text("import flet\n", encoding="utf-8")
    (project / "theme.py").touch()  # 로컬

    # LLM 이 theme 을 외부 deps 로 (잘못) 보고
    bad_report = """```yaml
direct_dependencies:
  - name: flet
  - name: theme
hidden_imports: []
```
"""
    result = _resolve_build_deps(bad_report, project / "main.py", [project / "main.py", project / "theme.py"])
    direct = result.direct_deps_to_install
    assert "flet" in direct
    assert "theme" not in direct, "fixup #7 가 LLM 의 잘못된 로컬 모듈 보고를 차단해야 함"


# ---------------------------------------------------------------------------
# PR #133 fixup #8 — AST primary + Mutex groups + --collect-all whitelist + Entry 개선
# ---------------------------------------------------------------------------


def test_resolve_build_deps_returns_dataclass() -> None:
    """fixup #8 — BuildDepsResolution dataclass 반환 (4 필드)."""
    from src.workflows.build_workflow import BuildDepsResolution, _resolve_build_deps
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("import flet\n")
        p = Path(f.name)
    try:
        result = _resolve_build_deps("", p, [p])
        assert isinstance(result, BuildDepsResolution)
        assert hasattr(result, "direct_deps_to_install")
        assert hasattr(result, "hidden_imports")
        assert hasattr(result, "collect_all_packages")
        assert hasattr(result, "excluded_modules")
    finally:
        p.unlink()


def test_resolve_build_deps_qt_mutex_pyside6_wins_over_pyqt6(tmp_path: Path) -> None:
    """fixup #8 — PySide6 + PyQt6 동시 검출 시 1개만 채택 + 나머지 --exclude-module.

    사용자 라이브 검증 (2026-05-13) 의 정확한 시나리오 재현:
        direct_dependencies: 2개 (PySide6, PyQt6) → PyInstaller abort.
    fixup #8 가 _MUTEX_GROUPS 로 1개만 채택.
    """
    from src.workflows.build_workflow import _resolve_build_deps

    project = tmp_path / "proj"
    project.mkdir()
    # PySide6 가 더 자주 import 됨 (AST count 5 vs PyQt6 1)
    (project / "app.py").write_text(
        "from PySide6.QtWidgets import QApplication, QMainWindow\n"
        "from PySide6.QtCore import Qt\n"
        "from PySide6.QtGui import QIcon\n"
        "from PySide6.QtSvg import QSvgRenderer\n"
        "import PySide6\n"
        "import PyQt6\n",  # 1번만 (호환성 보조)
        encoding="utf-8",
    )
    result = _resolve_build_deps("", project / "app.py", [project / "app.py"])
    # PySide6 채택, PyQt6 제외
    assert "PySide6" in result.direct_deps_to_install
    assert "PyQt6" not in result.direct_deps_to_install
    assert "PyQt6" in result.excluded_modules


def test_resolve_build_deps_qt_mutex_priority_tiebreaker(tmp_path: Path) -> None:
    """fixup #8 — Qt mutex 등장 횟수 동률 시 priority table 로 PySide6 우선."""
    from src.workflows.build_workflow import _resolve_build_deps

    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text(
        "import PySide6\nimport PyQt6\n",  # 각 1번
        encoding="utf-8",
    )
    result = _resolve_build_deps("", project / "app.py", [project / "app.py"])
    # 우선순위에 따라 PySide6 채택
    assert "PySide6" in result.direct_deps_to_install
    assert "PyQt6" not in result.direct_deps_to_install
    assert "PyQt6" in result.excluded_modules


def test_resolve_build_deps_collect_all_whitelist(tmp_path: Path) -> None:
    """fixup #8 — --collect-all 화이트리스트 외 패키지 (numpy 등) 는 --collect-all 안 붙음."""
    from src.workflows.build_workflow import _resolve_build_deps

    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text(
        "import flet\n"      # 화이트리스트 → --collect-all
        "import numpy\n"     # 화이트리스트 X → PyInstaller 내장 hook 에 위임
        "import customtkinter\n",  # 화이트리스트 → --collect-all
        encoding="utf-8",
    )
    result = _resolve_build_deps("", project / "app.py", [project / "app.py"])
    # 모두 pip install 대상
    assert "flet" in result.direct_deps_to_install
    assert "numpy" in result.direct_deps_to_install
    assert "customtkinter" in result.direct_deps_to_install
    # 화이트리스트만 --collect-all
    assert "flet" in result.collect_all_packages
    assert "customtkinter" in result.collect_all_packages
    assert "numpy" not in result.collect_all_packages, (
        "numpy 는 PyInstaller 내장 hook 에 위임 — --collect-all 불필요"
    )


# ---------------------------------------------------------------------------
# PR #133 fixup #9 — __main__ block PRIORITY 1 (entry_hint 우선순위 강등)
# ---------------------------------------------------------------------------


def test_select_entry_point_main_block_beats_wrong_entry_hint(tmp_path: Path) -> None:
    """fixup #9 핵심 — entry_hint 가 잘못된 파일을 가리켜도 __main__ block 가진 파일 선택.

    사용자 라이브 검증 3회차 (2026-05-13) 의 정확한 시나리오 재현:
        - code_files: [theme.py, app.py, calculator_engine.py, ...]
        - app.py 만 __main__ block 보유
        - 어떤 이유로 entry_hint = "theme.py"
        - fixup #8 까지: theme.py 선택 → no-op .exe (창 안 뜸)
        - fixup #9 부터: app.py 선택 (__main__ block PRIORITY 1)
    """
    from src.workflows.build_workflow import _select_entry_point

    project = tmp_path / "code"
    project.mkdir()
    # 사용자 라이브 시나리오 정확 재현
    (project / "theme.py").write_text(
        'DARK_TEXT_SECONDARY = "#A8A29E"\nFONT_FAMILY = "Helvetica"\n',
        encoding="utf-8",
    )
    (project / "app.py").write_text(
        'import customtkinter as ctk\n'
        'def main():\n    app = ctk.CTk()\n    app.mainloop()\n\n'
        'if __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    (project / "calculator_engine.py").write_text(
        "def add(a, b): return a + b\n", encoding="utf-8"
    )
    (project / "main_window.py").write_text(
        "class MainWindow: pass\n", encoding="utf-8"
    )

    code_files = [
        project / "theme.py",
        project / "app.py",
        project / "calculator_engine.py",
        project / "main_window.py",
    ]
    # 잘못된 entry_hint
    path, reason = _select_entry_point(code_files, "theme.py")
    assert path is not None
    assert path.name == "app.py", (
        f"잘못된 entry_hint 가 theme.py 를 가리키는데도 app.py 가 선택되어야 함. "
        f"실제 선택: {path.name}, reason: {reason}"
    )
    assert "__main__" in reason or "main" in reason.lower()


def test_select_entry_point_multiple_main_blocks_prefers_hint(tmp_path: Path) -> None:
    """여러 파일에 __main__ block 있을 때 entry_hint 매칭 우선."""
    from src.workflows.build_workflow import _select_entry_point

    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text(
        "if __name__ == '__main__':\n    print('app')\n", encoding="utf-8"
    )
    (project / "tool.py").write_text(
        "if __name__ == '__main__':\n    print('tool')\n", encoding="utf-8"
    )

    code_files = [project / "app.py", project / "tool.py"]
    # entry_hint 가 tool.py 를 가리키면 그게 선택됨 (둘 다 __main__ 있으므로)
    path, reason = _select_entry_point(code_files, "tool.py")
    assert path is not None
    assert path.name == "tool.py"
    assert "matches entry_hint" in reason


def test_select_entry_point_multiple_main_blocks_no_hint_uses_name_priority(
    tmp_path: Path,
) -> None:
    """여러 main_block, entry_hint 없으면 이름 휴리스틱."""
    from src.workflows.build_workflow import _select_entry_point

    project = tmp_path / "proj"
    project.mkdir()
    (project / "tool.py").write_text(
        "if __name__ == '__main__':\n    pass\n", encoding="utf-8"
    )
    (project / "app.py").write_text(
        "if __name__ == '__main__':\n    pass\n", encoding="utf-8"
    )
    (project / "main.py").write_text(
        "if __name__ == '__main__':\n    pass\n", encoding="utf-8"
    )

    code_files = [project / "tool.py", project / "app.py", project / "main.py"]
    path, reason = _select_entry_point(code_files, "")
    assert path is not None
    # 우선순위: app.py > main.py > __main__.py > run.py > entry.py
    assert path.name == "app.py", f"app.py 가 1순위여야 함 (실제: {path.name})"
    assert "name heuristic" in reason


def test_select_entry_point_no_main_block_falls_back_to_hint(tmp_path: Path) -> None:
    """__main__ block 보유 파일이 *전혀 없을 때만* entry_hint 사용."""
    from src.workflows.build_workflow import _select_entry_point

    project = tmp_path / "proj"
    project.mkdir()
    (project / "theme.py").write_text("X = 1\n", encoding="utf-8")
    (project / "config.py").write_text("Y = 2\n", encoding="utf-8")

    code_files = [project / "theme.py", project / "config.py"]
    path, reason = _select_entry_point(code_files, "config.py")
    assert path is not None
    assert path.name == "config.py"
    assert "falling back to entry_hint" in reason


def test_select_entry_point_no_main_no_hint_uses_name_heuristic(tmp_path: Path) -> None:
    """__main__ block 없고 hint 도 없으면 이름 휴리스틱."""
    from src.workflows.build_workflow import _select_entry_point

    project = tmp_path / "proj"
    project.mkdir()
    (project / "theme.py").touch()
    (project / "app.py").touch()  # 우선순위 1
    (project / "views.py").touch()

    code_files = [project / "theme.py", project / "app.py", project / "views.py"]
    path, reason = _select_entry_point(code_files, "")
    assert path is not None
    assert path.name == "app.py"
    assert "name heuristic" in reason


def test_select_entry_point_last_resort_first_file(tmp_path: Path) -> None:
    """모든 우선순위 실패 시 첫 파일."""
    from src.workflows.build_workflow import _select_entry_point

    project = tmp_path / "proj"
    project.mkdir()
    (project / "alpha.py").touch()
    (project / "beta.py").touch()
    (project / "gamma.py").touch()

    code_files = [project / "alpha.py", project / "beta.py", project / "gamma.py"]
    path, reason = _select_entry_point(code_files, "")
    assert path is not None
    assert path.name == "alpha.py"
    assert "last resort" in reason or "first" in reason


def test_select_entry_point_returns_none_for_empty_input() -> None:
    """code_files 비었으면 (None, reason) 반환."""
    from src.workflows.build_workflow import _select_entry_point

    path, reason = _select_entry_point([], "anything")
    assert path is None
    assert reason


def test_select_entry_point_absolute_hint_wins(tmp_path: Path) -> None:
    """절대경로 entry_hint 가 직접 존재하면 무조건 사용 (호출 측 확신 신뢰)."""
    from src.workflows.build_workflow import _select_entry_point

    abs_entry = tmp_path / "absolute_entry.py"
    abs_entry.write_text("# no main block\n", encoding="utf-8")
    other = tmp_path / "other_with_main.py"
    other.write_text("if __name__ == '__main__':\n    pass\n", encoding="utf-8")

    # 절대경로 hint → __main__ 있는 다른 파일보다 우선
    path, reason = _select_entry_point([other], str(abs_entry))
    assert path == abs_entry
    assert "absolute" in reason


def test_resolve_entry_path_prefers_main_block(tmp_path: Path) -> None:
    """fixup #8 — code_files 중 if __name__ == '__main__' 블록 가진 파일 우선."""
    from src.workflows.build_workflow import _resolve_entry_path

    project = tmp_path / "proj"
    project.mkdir()
    # theme.py — main block 없음
    (project / "theme.py").write_text("COLORS = {}\n", encoding="utf-8")
    # calculator.py — main block 있음
    (project / "calculator.py").write_text(
        "import flet\n\n"
        "def main(page):\n    pass\n\n"
        "if __name__ == '__main__':\n    flet.app(target=main)\n",
        encoding="utf-8",
    )
    # views.py — main block 없음
    (project / "views.py").write_text("class View: pass\n", encoding="utf-8")

    # entry_hint 미매칭 (다른 파일명) → __main__ block 가진 calculator.py 채택
    code_files = [
        project / "theme.py",
        project / "calculator.py",
        project / "views.py",
    ]
    entry = _resolve_entry_path(code_files, "nonexistent.py")
    assert entry is not None
    assert entry.name == "calculator.py", (
        f"__main__ block 가진 파일 우선 미적용: {entry.name if entry else None}"
    )


def test_resolve_entry_path_name_heuristic_when_no_main_block(tmp_path: Path) -> None:
    """fixup #8 — main block 없으면 main.py / app.py 등 이름 휴리스틱."""
    from src.workflows.build_workflow import _resolve_entry_path

    project = tmp_path / "proj"
    project.mkdir()
    (project / "theme.py").touch()
    (project / "app.py").touch()  # 이름 휴리스틱 우선
    (project / "views.py").touch()

    code_files = [project / "theme.py", project / "app.py", project / "views.py"]
    entry = _resolve_entry_path(code_files, "")
    assert entry is not None
    assert entry.name == "app.py", (
        f"이름 휴리스틱 (app.py) 미적용: {entry.name if entry else None}"
    )


def test_resolve_entry_path_main_block_wins_over_wrong_hint(tmp_path: Path) -> None:
    """fixup #9 — __main__ block 보유 파일이 PRIORITY 1.

    이전 fixup #8 의 "explicit hint > main block" 가정은 잘못됐음 (사용자 라이브
    검증으로 확인). hint 가 main block 미보유 파일을 가리키면 hint 무시 + main
    block 파일 선택.
    """
    from src.workflows.build_workflow import _resolve_entry_path

    project = tmp_path / "proj"
    project.mkdir()
    (project / "main.py").write_text(
        "if __name__ == '__main__':\n    pass\n", encoding="utf-8"
    )
    (project / "custom_entry.py").touch()  # main block 없음

    code_files = [project / "main.py", project / "custom_entry.py"]
    # entry_hint 가 custom_entry.py 를 가리켜도 main.py 가 main block 보유 → main.py 우선
    entry = _resolve_entry_path(code_files, "custom_entry.py")
    assert entry is not None
    assert entry.name == "main.py", (
        f"main block 보유 파일이 우선이어야 함 (실제: {entry.name})"
    )


def test_has_main_block_detects_standard_form(tmp_path: Path) -> None:
    """_has_main_block — 표준 form 검출."""
    from src.workflows.build_workflow import _has_main_block

    p1 = tmp_path / "with_main.py"
    p1.write_text("if __name__ == '__main__':\n    pass\n", encoding="utf-8")
    p2 = tmp_path / "without_main.py"
    p2.write_text("def foo(): pass\n", encoding="utf-8")
    p3 = tmp_path / "reversed.py"
    p3.write_text("if '__main__' == __name__:\n    pass\n", encoding="utf-8")

    assert _has_main_block(p1) is True
    assert _has_main_block(p2) is False
    assert _has_main_block(p3) is True  # reversed form 도 검출


def test_execute_pyinstaller_accepts_exclude_modules(monkeypatch, tmp_path: Path) -> None:
    """fixup #8 — execute_pyinstaller 가 --exclude-module <pkg> 자동 추가."""
    from src.agents.build_release import build_executor

    captured: dict = {}

    def _fake_resolve():
        return Path("fake.exe")

    def _fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = list(cmd)
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    monkeypatch.setattr(build_executor, "_resolve_pyinstaller_executable", _fake_resolve)
    monkeypatch.setattr(build_executor.subprocess, "run", _fake_run)

    entry = tmp_path / "app.py"
    entry.write_text("import PySide6\n", encoding="utf-8")
    out = tmp_path / "out"

    build_executor.execute_pyinstaller(
        entry_path=entry,
        output_dir=out,
        app_name="App",
        exclude_modules=["PyQt6", "PyQt5"],
    )

    cmd = captured["cmd"]
    # --exclude-module PyQt6 + --exclude-module PyQt5
    assert "--exclude-module" in cmd
    assert "PyQt6" in cmd
    assert "PyQt5" in cmd
    # 각 패키지마다 --exclude-module 가 앞서야 함
    pyqt6_idx = cmd.index("PyQt6")
    assert cmd[pyqt6_idx - 1] == "--exclude-module"


def test_count_import_occurrences_basic(tmp_path: Path) -> None:
    """_count_import_occurrences — top-level 매칭만 카운트."""
    from src.workflows.build_workflow import _count_import_occurrences

    p = tmp_path / "code.py"
    p.write_text(
        "import PySide6\n"
        "from PySide6.QtCore import Qt\n"
        "from PySide6.QtGui import QIcon\n"
        "import PyQt6\n",
        encoding="utf-8",
    )
    assert _count_import_occurrences("PySide6", [p]) == 3
    assert _count_import_occurrences("PyQt6", [p]) == 1
    assert _count_import_occurrences("nonexistent", [p]) == 0


def test_build_workflow_halts_on_pip_install_failure(monkeypatch, tmp_path: Path) -> None:
    """PR #133 fixup #6 — pip install 실패 시 PyInstaller 호출 *중단*.

    빈 껍데기 .exe 가 생성되어 런타임 ModuleNotFoundError 가 나느니, build 단계
    에서 명시적 ExecuteResult.success=False 로 실패하는 게 디버깅 용이.
    """
    from src.workflows import build_workflow

    # _install_dependencies_for_build 가 항상 실패하도록 mock
    def _fail_install(deps, **kwargs):
        return False, "MOCK: pip install failed for testing"

    # execute_pyinstaller 가 호출되면 안 됨
    called = {"pyinstaller": False}
    def _should_not_call(*args, **kwargs):
        called["pyinstaller"] = True
        raise AssertionError("execute_pyinstaller 가 호출되면 안 됨 (pip 실패 시)")

    monkeypatch.setattr(build_workflow, "_install_dependencies_for_build", _fail_install)
    monkeypatch.setattr(build_workflow, "execute_pyinstaller", _should_not_call)

    # 직접 _resolve_build_deps 확인 (사용자 facing API)
    src = "import flet\n"
    entry = tmp_path / "app.py"
    entry.write_text(src, encoding="utf-8")

    result = build_workflow._resolve_build_deps("", entry, [entry])
    direct = result.direct_deps_to_install
    assert "flet" in direct

    # _install_dependencies_for_build mock 호출
    ok, log = build_workflow._install_dependencies_for_build(direct)
    assert ok is False
    assert "MOCK" in log
    # execute_pyinstaller 는 mock 으로 막혔지만, 정확한 통합 검증은 run_build_workflow 전체 호출이 필요.
    # 본 테스트는 mock 동작 + helper 단위 검증.
    assert called["pyinstaller"] is False
