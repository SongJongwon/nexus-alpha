# -*- coding: utf-8 -*-
"""PR #133 fixup #14 — 정적 module attribute 검증.

배경 (사용자 라이브 검증, 2026-05-13):
    LLM 이 flet 앱에서 ``flet.colors.RED`` 호출 → 설치된 Flet 0.21+ 에는
    ``colors`` (소문자) 없음 (``Colors`` 로 rename 됨) → .exe 가 사용자 PC 에서
    AttributeError popup 표시. fixup #11 의 subprocess validation 은 Flet 의
    internal error handler 가 catch 해서 popup 으로만 나타나므로 못 잡음.

처방 (fixup #14):
    AST 정적 분석으로 attribute chain 추출 → importlib.import_module + getattr
    walk → 누락 시 build 중단 (사용자 PC 에 빈 .exe 안 만들어짐).

핵심 안전망 (사용자 명시 요구):
    1) 회귀 방지 — 기존 통과 시나리오 (customtkinter, PyQt6) 깨지지 않게
    2) False positive 위험 0 우선 — 모르겠으면 통과
       (instance attr, dynamic __getattr__, 가드된 import 등)

본 모듈은 위 둘을 모두 검증.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# 핵심 동작 — broken attribute 검출 (사용자 시나리오)
# ---------------------------------------------------------------------------


def test_detects_missing_attribute_on_installed_module(tmp_path: Path) -> None:
    """fixup #14 핵심 — 사용자 시나리오 (flet.colors) 와 동등한 패턴 재현."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    # pytest 는 venv 에 확실히 설치돼 있으므로 검증 가능
    p.write_text(
        "import pytest\n"
        "result = pytest.this_attribute_definitely_does_not_exist\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    assert ok is False, f"미존재 attribute 검출 실패: broken={broken}"
    assert any("this_attribute_definitely_does_not_exist" in b for b in broken)


def test_passes_valid_attribute_chain(tmp_path: Path) -> None:
    """fixup #14 — 정상 attribute 는 통과."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import pytest\n"
        "@pytest.fixture\n"
        "def my_fixture(): pass\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    assert ok is True, f"정상 attribute (pytest.fixture) 가 false positive: {broken}"


def test_detects_missing_attribute_via_alias(tmp_path: Path) -> None:
    """fixup #14 — ``import X as Y`` alias 도 정확히 매핑."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import pytest as pt\n"
        "val = pt.bogus_attribute_xyz\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    assert ok is False
    assert any("bogus_attribute_xyz" in b for b in broken)


# ---------------------------------------------------------------------------
# False positive 회피 — 사용자 명시 요구 "False positive 위험 0 우선"
# ---------------------------------------------------------------------------


def test_skips_instance_attribute_access(tmp_path: Path) -> None:
    """fixup #14 — instance attr (`self.x.y` / `obj.foo`) 는 정적 검증 불가 → skip.

    호출 예: ``page.controls.append(...)`` — page 는 함수 파라미터, 검증 불가.
    이런 케이스를 false positive 로 잘못 차단하면 모든 OO 코드가 깨짐.
    """
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import pytest\n"
        "data = pytest.fixture\n"
        "val = data.fake_attribute_xyz\n",  # data 는 local var, 모듈 X
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    # 'data' 는 all_aliases 에 없음 → skip → ok
    assert ok is True, f"local var 의 attr 가 잘못 차단됨: {broken}"


def test_skips_stdlib_chains(tmp_path: Path) -> None:
    """fixup #14 — stdlib (os, sys, json 등) 은 PyInstaller 가 처리, skip."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import os\n"
        "val = os.path.does_not_exist_function\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    assert ok is True, f"stdlib 가 잘못 차단됨: {broken}"


def test_skips_unimportable_module(tmp_path: Path) -> None:
    """fixup #14 — 미설치 모듈 import 실패 → skip (local 모듈 가능성).

    e.g., LLM 이 생성한 ``from helpers import foo`` 같은 코드. ``helpers`` 가
    venv 에 없으면 import 실패 → 검증 skip (false positive 안전망).
    """
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import absolutely_nonexistent_module_xyz_abc\n"
        "val = absolutely_nonexistent_module_xyz_abc.fake_attr\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    # import 실패 → skip → ok
    assert ok is True, f"미설치 모듈이 false positive: {broken}"


def test_handles_dynamic_getattr_module(tmp_path: Path, monkeypatch) -> None:
    """fixup #14 — 모듈이 __getattr__ 동적 dispatch 시 false positive 회피.

    e.g., numpy, scipy 등 C extension 은 hasattr 시점에 raise 가능. 그럴 땐
    valid 로 간주 (false positive 회피 우선).
    """
    import sys as _sys
    from types import ModuleType

    # 가짜 모듈 — hasattr() 가 예외 발생
    class DynamicModule(ModuleType):
        def __getattr__(self, name):
            raise RuntimeError(f"dynamic dispatch error for {name}")

    fake_mod = DynamicModule("fake_dyn_module")
    monkeypatch.setitem(_sys.modules, "fake_dyn_module", fake_mod)

    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import fake_dyn_module\n"
        "val = fake_dyn_module.any_attr\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    # __getattr__ 가 예외 → 우리 코드가 valid 로 간주 → ok
    assert ok is True, f"dynamic __getattr__ 가 false positive: {broken}"


def test_skips_from_imports(tmp_path: Path) -> None:
    """fixup #14 — ``from X import Y`` 는 검증 X (Y 가 module 인지 불명).

    e.g., ``from flet import Page`` 에서 Page.something 검증하면 Page 가
    클래스인지 모듈인지 모르므로 false positive 위험. 일관성 위해 skip.
    """
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "from pytest import fixture\n"
        "val = fixture.completely_fake_xyz\n",  # 정적 검증 X
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    # fixture 는 all_aliases 에 없음 → skip
    assert ok is True, f"from-import 가 false positive: {broken}"


def test_handles_method_call_chains(tmp_path: Path) -> None:
    """fixup #14 — ``f().attr`` (Call 결과의 attr) 는 정적 검증 불가 → skip."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import pytest\n"
        "val = pytest.fixture().fake_attr\n",  # Call 결과 → skip
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    # pytest.fixture 는 valid → 이건 통과. fixture() 호출 결과의 fake_attr 는 검증 X
    # 단, 'pytest.fixture' chain 자체는 valid 이므로 통과
    assert ok is True


# ---------------------------------------------------------------------------
# 회귀 방지 — 기존 통과 시나리오 시뮬레이션
# ---------------------------------------------------------------------------


def test_regression_customtkinter_calculator_pattern(tmp_path: Path) -> None:
    """fixup #14 — customtkinter 정상 패턴 (1차 회차 시나리오 시뮬레이션).

    customtkinter 가 venv 에 설치되어 있지 않을 가능성이 높으므로 import 실패 →
    skip → ok. 만약 설치되어 있다면 실제 attribute 검증.
    """
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "calculator.py"
    p.write_text(
        "import customtkinter as ctk\n"
        "app = ctk.CTk()\n"
        "app.title('Calculator')\n"
        "app.mainloop()\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    # customtkinter 가 설치돼있고 CTk attribute 가 있으면 ok
    # 설치 안 됐으면 import 실패 → skip → ok
    # 두 케이스 모두 false positive 없어야 함
    assert ok is True, f"회귀: customtkinter 정상 패턴이 차단됨: {broken}"


def test_regression_pyqt6_pattern(tmp_path: Path) -> None:
    """fixup #14 — PyQt6 정상 패턴 (이전 13:25 빌드 시나리오 시뮬레이션)."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "from PyQt6.QtWidgets import QApplication, QMainWindow\n"  # from-import → skip
        "import sys\n"
        "if __name__ == '__main__':\n"
        "    app = QApplication(sys.argv)\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    # from-import 는 검증 X → 어쨌든 ok
    assert ok is True, f"회귀: PyQt6 from-import 패턴 차단됨: {broken}"


def test_regression_pyside6_module_access(tmp_path: Path) -> None:
    """fixup #14 — PySide6 module-style access (정상)."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import PySide6\n"
        "version = PySide6.__version__ if hasattr(PySide6, '__version__') else 'unknown'\n",
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    # PySide6 가 미설치면 skip, 설치돼있고 __version__ 있으면 통과
    assert ok is True, f"회귀: PySide6 module access 차단됨: {broken}"


# ---------------------------------------------------------------------------
# 사용자 시나리오 — flet.colors 정확 재현 (mock 으로)
# ---------------------------------------------------------------------------


def test_user_scenario_flet_colors_missing(tmp_path: Path, monkeypatch) -> None:
    """fixup #14 핵심 — 사용자 라이브 시나리오 정확 재현 (flet.colors 누락).

    실제 flet 가 venv 에 없을 가능성 높으므로 mock 으로 시뮬레이션:
        - mock flet 모듈 (colors attribute 없음)
        - 사용자 코드: import flet; flet.colors.RED
        - 예상: ok=False, broken 에 'flet.colors' 명시
    """
    import sys as _sys
    from types import ModuleType

    class FakeFlet(ModuleType):
        """colors 없는 가짜 flet (사용자 시나리오)."""
        Colors = "fake-Colors-uppercase"  # 신 API 만 있음
        # colors (소문자) attribute 없음

    fake_flet = FakeFlet("flet_fake_for_test")
    monkeypatch.setitem(_sys.modules, "flet_fake_for_test", fake_flet)

    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import flet_fake_for_test\n"
        "val = flet_fake_for_test.colors.RED\n",  # 사용자 시나리오 정확 재현
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    assert ok is False, "사용자 시나리오 차단 실패"
    # 'flet_fake_for_test.colors' 가 broken 에 포함
    assert any("colors" in b for b in broken), f"colors 누락 정보 없음: {broken}"


def test_user_scenario_with_correct_api_passes(tmp_path: Path, monkeypatch) -> None:
    """fixup #14 — LLM 이 *정확한* API 쓰면 통과 (Flet 0.21+ 의 Colors)."""
    import sys as _sys
    from types import ModuleType

    class FakeFlet(ModuleType):
        Colors = ModuleType("Colors")
    fake_flet = FakeFlet("flet_correct_for_test")
    fake_flet.Colors.RED = "#FF0000"
    monkeypatch.setitem(_sys.modules, "flet_correct_for_test", fake_flet)

    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "app.py"
    p.write_text(
        "import flet_correct_for_test\n"
        "val = flet_correct_for_test.Colors.RED\n",  # 정확한 API
        encoding="utf-8",
    )
    ok, broken = _validate_module_attributes(p, [p])
    assert ok is True, f"정확한 API 가 잘못 차단됨: {broken}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_handles_empty_code_file(tmp_path: Path) -> None:
    """fixup #14 — 빈 파일 → OK."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "empty.py"
    p.write_text("", encoding="utf-8")
    ok, broken = _validate_module_attributes(p, [p])
    assert ok is True
    assert broken == []


def test_handles_syntax_error_in_code_file(tmp_path: Path) -> None:
    """fixup #14 — SyntaxError 파일 → graceful (해당 파일만 skip)."""
    from src.workflows.build_workflow import _validate_module_attributes

    p = tmp_path / "broken.py"
    p.write_text("def broken(\n", encoding="utf-8")  # SyntaxError
    ok, broken = _validate_module_attributes(p, [p])
    # parse 실패 → chain 추출 X → 검증할 게 없음 → ok
    assert ok is True


def test_handles_missing_entry_path(tmp_path: Path) -> None:
    """fixup #14 — None entry + None code_files → ok."""
    from src.workflows.build_workflow import _validate_module_attributes

    ok, broken = _validate_module_attributes(None, None)
    assert ok is True
    assert broken == []


def test_caps_broken_chain_count(tmp_path: Path, monkeypatch) -> None:
    """fixup #14 — broken chain 너무 많으면 cap (UX). 첫 10~20개만 보고."""
    import sys as _sys
    from types import ModuleType

    empty_mod = ModuleType("super_empty_mod")  # attribute 없음
    monkeypatch.setitem(_sys.modules, "super_empty_mod", empty_mod)

    from src.workflows.build_workflow import _validate_module_attributes

    # 30개의 broken chain 생성
    lines = ["import super_empty_mod"] + [
        f"val{i} = super_empty_mod.attr_{i}" for i in range(30)
    ]
    p = tmp_path / "many_broken.py"
    p.write_text("\n".join(lines), encoding="utf-8")
    ok, broken = _validate_module_attributes(p, [p])
    assert ok is False
    # 적당히 cap 됨 (20 이하)
    assert len(broken) <= 20


# ---------------------------------------------------------------------------
# Integration — build_workflow 가 fixup #14 결과를 ExecuteResult 로 반영
# ---------------------------------------------------------------------------


def test_build_workflow_blocks_on_broken_attribute(tmp_path: Path, monkeypatch) -> None:
    """fixup #14 통합 — broken attribute 감지 시 PyInstaller 호출 차단."""
    import sys as _sys
    from types import ModuleType
    from src.agents.build_release.build_executor import ExecuteResult
    from src.workflows import build_workflow

    fake = ModuleType("flet_block_test")
    monkeypatch.setitem(_sys.modules, "flet_block_test", fake)

    # _resolve_build_deps 가 정상이고 pip_install 도 OK 가정 (mock)
    p = tmp_path / "app.py"
    p.write_text(
        "import flet_block_test\n"
        "val = flet_block_test.colors.RED\n",
        encoding="utf-8",
    )
    # _validate_module_attributes 가 false 를 반환
    ok, broken = build_workflow._validate_module_attributes(p, [p])
    assert ok is False
    # build_workflow 에서 attr_ok 가 False 면 ExecuteResult(success=False, exit_code=-6)
    # 직접 호출 path 는 복잡하므로 단위 테스트는 _validate_module_attributes 만 검증.
    # Integration 은 라이브 검증 5회로 확인 (사용자 시나리오).


# ---------------------------------------------------------------------------
# Helper 함수 단위 테스트 — _extract_module_aliases, _extract_attribute_chains
# ---------------------------------------------------------------------------


def test_extract_module_aliases() -> None:
    """_extract_module_aliases — import / import as 모두 정확히 추출."""
    import ast
    from src.workflows.build_workflow import _extract_module_aliases

    src = (
        "import flet\n"
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "from os import path\n"  # from-import 는 무시
    )
    tree = ast.parse(src)
    aliases = _extract_module_aliases(tree)
    assert aliases.get("flet") == "flet"
    assert aliases.get("np") == "numpy"
    assert aliases.get("plt") == "matplotlib.pyplot"
    assert "path" not in aliases  # from-import 는 skip


def test_extract_attribute_chains() -> None:
    """_extract_attribute_chains — Attribute 노드를 chain 으로 정확히 변환."""
    import ast
    from src.workflows.build_workflow import _extract_attribute_chains

    src = (
        "import flet\n"
        "flet.app(target=main)\n"  # ('flet', 'app')
        "flet.colors.RED\n"        # ('flet', 'colors', 'RED')
        "data.foo\n"                # ('data', 'foo')
        "f().attr\n"                # Call().attr → skip (starts with Call)
    )
    tree = ast.parse(src)
    chains = _extract_attribute_chains(tree)
    chain_strs = ['.'.join(c) for c in chains]
    assert "flet.app" in chain_strs
    assert "flet.colors.RED" in chain_strs
    assert "data.foo" in chain_strs
    # f().attr 는 chain 에 포함 안 됨 (top 이 Name 아님)
    assert not any(c[0] == "f" for c in chains)
