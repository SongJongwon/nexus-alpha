# -*- coding: utf-8 -*-
"""PR #210 회귀 차단 — AST 기반 GUI 감지 + .exe smoke test.

PM 명시 (2026-05-26, 4회 BLOCKED 사고 처방):
    - 이전 PR #209 의 substring grep 한계 (false positive: 주석/문자열) 극복
    - AST `ast.walk` + `ast.Import` / `ast.ImportFrom` 으로 *실제 import 만* 검출
    - .exe smoke test — 3초 alive = PASS, 즉시 종료 = FAIL (theme.py entry 오선택 차단)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.agents.build_release.build_executor import (
    SmokeTestResult,
    run_exe_smoke_test,
)
from src.workflows.iterative_loop import (
    _ast_detect_gui_in_code,
    _detect_gui_in_saved_files,
    _substring_detect_gui_in_code,
)


# ============================================================================
# AST GUI Detection
# ============================================================================


class TestASTGuiDetection:
    """`_ast_detect_gui_in_code` — AST 기반 GUI framework import 검출."""

    def test_tkinter_simple_import(self):
        code = "import tkinter\nroot = tkinter.Tk()"
        assert _ast_detect_gui_in_code(code) is True

    def test_tkinter_alias(self):
        code = "import tkinter as tk\nroot = tk.Tk()"
        assert _ast_detect_gui_in_code(code) is True

    def test_tkinter_from(self):
        code = "from tkinter import Tk, Frame\nroot = Tk()"
        assert _ast_detect_gui_in_code(code) is True

    def test_tkinter_ttk_submodule(self):
        """tkinter.ttk 같은 submodule 도 top-level 'tkinter' 매치 → True."""
        code = "from tkinter.ttk import Button"
        assert _ast_detect_gui_in_code(code) is True

    def test_flet(self):
        code = "import flet as ft\nft.app(target=lambda p: None)"
        assert _ast_detect_gui_in_code(code) is True

    def test_pyqt6(self):
        code = "from PyQt6.QtWidgets import QApplication, QMainWindow"
        assert _ast_detect_gui_in_code(code) is True

    def test_pyside6(self):
        code = "import PySide6.QtCore"
        assert _ast_detect_gui_in_code(code) is True

    def test_customtkinter(self):
        code = "import customtkinter as ctk\nctk.CTk()"
        assert _ast_detect_gui_in_code(code) is True

    def test_kivy(self):
        code = "from kivy.app import App"
        assert _ast_detect_gui_in_code(code) is True

    def test_wx(self):
        code = "import wx\napp = wx.App()"
        assert _ast_detect_gui_in_code(code) is True

    def test_ttkbootstrap(self):
        """ttkbootstrap 도 tkinter 기반 — 동일 mainloop 문제 → True."""
        code = "import ttkbootstrap as ttk"
        assert _ast_detect_gui_in_code(code) is True

    def test_pygame(self):
        """pygame 도 event loop — True."""
        code = "import pygame\npygame.init()"
        assert _ast_detect_gui_in_code(code) is True

    def test_no_gui_pure_logic(self):
        code = "def add(a, b):\n    return a + b\n\nprint(add(1, 2))"
        assert _ast_detect_gui_in_code(code) is False

    def test_no_gui_stdlib_only(self):
        code = "import json\nimport os\nimport sys\nfrom pathlib import Path"
        assert _ast_detect_gui_in_code(code) is False

    def test_comment_no_false_positive(self):
        """⭐ PR #210 의 핵심 — 주석 안 'import tkinter' 는 false positive 안 됨.

        PR #209 substring grep 의 한계 — 본 케이스에서 잘못 True 였음.
        """
        code = (
            "# This file uses import tkinter? No, it doesn't.\n"
            "# Old version was: 'import tkinter as tk'\n"
            "def f(): pass\n"
        )
        assert _ast_detect_gui_in_code(code) is False

    def test_string_no_false_positive(self):
        """⭐ 문자열 안 'import tkinter' 도 false positive 안 됨."""
        code = "DOC = 'To use Tkinter, write: import tkinter as tk'\n"
        assert _ast_detect_gui_in_code(code) is False

    def test_docstring_no_false_positive(self):
        """⭐ docstring 안 marker 도 false positive 안 됨."""
        code = (
            '"""\n'
            "Module docstring.\n"
            "Example: import tkinter; import flet; import PyQt5.\n"
            '"""\n'
            "def f(): pass\n"
        )
        assert _ast_detect_gui_in_code(code) is False

    def test_syntax_error_falls_back_to_substring(self):
        """AST parse 실패 → substring fallback 으로 보수적 양성."""
        # 일부러 SyntaxError 유발 + tkinter 마커 포함
        code = "import tkinter\nthis is not valid python syntax !!!"
        assert _ast_detect_gui_in_code(code) is True  # fallback 으로 detect

    def test_empty_code(self):
        assert _ast_detect_gui_in_code("") is False

    def test_substring_fallback_helper(self):
        """`_substring_detect_gui_in_code` — backup helper."""
        assert _substring_detect_gui_in_code("import tkinter") is True
        assert _substring_detect_gui_in_code("from flet import App") is True
        assert _substring_detect_gui_in_code("def add(): pass") is False


# ============================================================================
# Multi-file Detection
# ============================================================================


class TestDetectGUIInSavedFiles:
    """`_detect_gui_in_saved_files` — 멀티파일 dict 검사."""

    def test_single_file_with_gui(self):
        files = {"app.py": "import tkinter\nroot = tkinter.Tk()"}
        assert _detect_gui_in_saved_files(files) is True

    def test_one_of_many_has_gui(self):
        files = {
            "logic.py": "def add(a, b):\n    return a + b",
            "ui.py": "import customtkinter as ctk\nctk.CTk()",
            "utils.py": "def helper(): pass",
        }
        assert _detect_gui_in_saved_files(files) is True

    def test_none_have_gui(self):
        files = {
            "app.py": "import json\nimport os",
            "lib.py": "def f(): pass",
            "models.py": "from dataclasses import dataclass",
        }
        assert _detect_gui_in_saved_files(files) is False

    def test_empty_dict(self):
        assert _detect_gui_in_saved_files({}) is False

    def test_none_input(self):
        assert _detect_gui_in_saved_files(None) is False

    def test_kanban_scenario(self):
        """⭐ PR #210 핵심 시나리오 — 칸반 보드 (PM 의 4번째 BLOCKED 사고)."""
        files = {
            "kanban_app.py": (
                "import tkinter as tk\n"
                "from tkinter import ttk\n"
                "class KanbanBoard(tk.Frame):\n"
                "    pass\n"
            ),
            "kanban_core.py": "class Board: pass",
            "kanban_storage.py": "import json\nimport os",
            "test_kanban.py": "def test_board(): pass",
        }
        assert _detect_gui_in_saved_files(files) is True


# ============================================================================
# .exe Smoke Test
# ============================================================================


class TestExeSmokeTest:
    """`run_exe_smoke_test` — 3초 alive = PASS, 즉시 종료 = FAIL."""

    def test_exe_not_found(self):
        fake = Path("C:/__nonexistent__/fake_app.exe")
        result = run_exe_smoke_test(fake)
        assert isinstance(result, SmokeTestResult)
        assert result.passed is False
        assert "미발견" in result.reason

    def test_dataclass_fields(self):
        """SmokeTestResult schema 검증."""
        result = SmokeTestResult(
            passed=True, reason="test", exit_code=None, survived_sec=3.0
        )
        assert result.passed is True
        assert result.reason == "test"
        assert result.exit_code is None
        assert result.survived_sec == 3.0

    @patch("src.agents.build_release.build_executor.subprocess.Popen")
    def test_passes_when_alive_for_timeout(self, mock_popen):
        """⭐ 3초 동안 살아있으면 PASS (GUI mainloop 시작 추정)."""
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(
            cmd=["fake.exe"], timeout=0.1
        )
        mock_popen.return_value = mock_proc

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tf:
            tf.write(b"fake binary")
            exe_path = Path(tf.name)
        try:
            result = run_exe_smoke_test(exe_path, timeout_sec=0.1)
            assert result.passed is True
            assert "alive" in result.reason
            mock_proc.terminate.assert_called_once()
        finally:
            exe_path.unlink(missing_ok=True)

    @patch("src.agents.build_release.build_executor.subprocess.Popen")
    def test_fails_when_exits_immediately(self, mock_popen):
        """⭐ 즉시 종료 (theme.py entry 오선택 사례) 는 FAIL."""
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0  # 즉시 종료
        mock_popen.return_value = mock_proc

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tf:
            tf.write(b"fake binary")
            exe_path = Path(tf.name)
        try:
            result = run_exe_smoke_test(exe_path, timeout_sec=3.0)
            assert result.passed is False
            assert "즉시 종료" in result.reason
        finally:
            exe_path.unlink(missing_ok=True)

    @patch("src.agents.build_release.build_executor.subprocess.Popen")
    def test_fails_when_spawn_raises(self, mock_popen):
        """spawn 자체 실패 (PermissionError 등) 도 FAIL."""
        mock_popen.side_effect = OSError("Permission denied")

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tf:
            tf.write(b"fake")
            exe_path = Path(tf.name)
        try:
            result = run_exe_smoke_test(exe_path)
            assert result.passed is False
            assert "spawn 실패" in result.reason
        finally:
            exe_path.unlink(missing_ok=True)

    @patch("src.agents.build_release.build_executor.subprocess.Popen")
    def test_fails_with_nonzero_exit(self, mock_popen):
        """exit_code != 0 도 FAIL — entry 가 import error 등으로 죽음."""
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 1  # 에러 종료
        mock_popen.return_value = mock_proc

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tf:
            tf.write(b"fake")
            exe_path = Path(tf.name)
        try:
            result = run_exe_smoke_test(exe_path, timeout_sec=2.0)
            assert result.passed is False
            assert result.exit_code == 1
        finally:
            exe_path.unlink(missing_ok=True)
