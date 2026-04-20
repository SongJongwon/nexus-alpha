# -*- coding: utf-8 -*-
"""
Phase 3 보강 — 멀티파일 패키지 sandbox 테스트.

검증 대상:
    1. 헤더 파서 `_extract_file_header` (5건)
    2. 경로 검증 `_sanitize_relpath` (5건)
    3. 트리 재구성 `_reconstruct_package_tree` (3건)
    4. Entry 탐지 `_detect_runnable_target` (4건)
    5. `run_python_package_in_sandbox` 통합 — 실제 subprocess (4건)
       * 단일 파일 PASS
       * `__main__.py` 패키지 + 상대 import PASS  ← 핵심 증명
       * `cli.py` fallback
       * 의도적 FAIL (traceback 캡처)

실행:
    .venv\\Scripts\\pytest.exe src\\tests\\test_sandbox_runner_package.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from src.agents.operations import SandboxResult, run_python_package_in_sandbox
from src.agents.operations.sandbox_runner import (
    _detect_runnable_target,
    _extract_file_header,
    _reconstruct_package_tree,
    _sanitize_relpath,
)


# =============================================================================
# 1. 헤더 파서
# =============================================================================
def test_extract_file_header_basic() -> None:
    assert _extract_file_header("# file: src/calc/cli.py\nprint('x')") == "src/calc/cli.py"


def test_extract_file_header_with_extra_spaces() -> None:
    assert _extract_file_header("#  file:   src/util.py  \n") == "src/util.py"


def test_extract_file_header_uppercase_keyword() -> None:
    """대소문자 무관 매칭 (LLM 출력 변형 대응)."""
    assert _extract_file_header("# FILE: src/x.py\n") == "src/x.py"


def test_extract_file_header_skips_blank_lines_above() -> None:
    """헤더가 첫 비어 있지 않은 줄에 있으면 통과 (상위 5줄 검사)."""
    text = "\n\n# file: src/a.py\nimport os\n"
    assert _extract_file_header(text) == "src/a.py"


def test_extract_file_header_returns_none_when_first_meaningful_line_isnt_header() -> None:
    """헤더가 아예 없으면 None — 첫 비어 있지 않은 줄만 보고 즉시 종료."""
    assert _extract_file_header("import os\n# file: src/x.py\nprint(1)") is None


# =============================================================================
# 2. 경로 검증
# =============================================================================
def test_sanitize_relpath_normal_relative() -> None:
    assert _sanitize_relpath("src/calc/cli.py") == "src/calc/cli.py"


def test_sanitize_relpath_normalizes_backslashes() -> None:
    """Windows 스타일 헤더(`src\\calc\\cli.py`)도 POSIX 로 정규화."""
    assert _sanitize_relpath("src\\calc\\cli.py") == "src/calc/cli.py"


def test_sanitize_relpath_rejects_absolute() -> None:
    assert _sanitize_relpath("/etc/passwd") is None
    assert _sanitize_relpath("C:/Windows/System32/foo.py") is None


def test_sanitize_relpath_rejects_traversal() -> None:
    assert _sanitize_relpath("../../etc/x.py") is None
    assert _sanitize_relpath("src/../../etc/x.py") is None


def test_sanitize_relpath_rejects_empty_or_null() -> None:
    assert _sanitize_relpath("") is None
    assert _sanitize_relpath("foo\x00bar.py") is None


# =============================================================================
# 3. 트리 재구성
# =============================================================================
def test_reconstruct_creates_nested_dirs(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    a = src_dir / "src__pkg____init__.py"
    a.write_text("# file: src/pkg/__init__.py\n")
    b = src_dir / "src__pkg__cli.py"
    b.write_text("# file: src/pkg/cli.py\nprint('hi')\n")

    workdir = tmp_path / "wd"
    workdir.mkdir()
    written = _reconstruct_package_tree([a, b], workdir)

    assert (workdir / "src" / "pkg" / "__init__.py").exists()
    assert (workdir / "src" / "pkg" / "cli.py").exists()
    assert len(written) == 2


def test_reconstruct_falls_back_to_root_when_no_header(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    a = src_dir / "calculator.py"
    a.write_text("print('no header')\n")  # 헤더 부재

    workdir = tmp_path / "wd"
    workdir.mkdir()
    written = _reconstruct_package_tree([a], workdir)

    assert (workdir / "calculator.py").exists()
    assert len(written) == 1


def test_reconstruct_skips_unsafe_paths(tmp_path: Path) -> None:
    """헤더가 절대 경로 또는 traversal 이면 skip — workdir 밖에 절대 작성하지 않음.

    악성 헤더는 .py 로 끝나야 헤더 파서를 통과해 sanitize 단계까지 도달:
    `# file: /etc/cron.d/payload.py` (절대) / `# file: ../../escape.py` (traversal).
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    bad_abs = src_dir / "evil_abs.py"
    bad_abs.write_text("# file: /etc/cron.d/payload.py\nprint('absolute pwn')\n")
    bad_traversal = src_dir / "evil_traversal.py"
    bad_traversal.write_text("# file: ../../escape.py\nprint('traversal pwn')\n")
    good = src_dir / "ok.py"
    good.write_text("# file: ok.py\nprint('ok')\n")

    workdir = tmp_path / "wd"
    workdir.mkdir()
    written = _reconstruct_package_tree([bad_abs, bad_traversal, good], workdir)

    assert (workdir / "ok.py").exists()
    # workdir 외부 어디에도 작성되지 않아야 함
    assert not (tmp_path.parent / "escape.py").exists()
    assert len(written) == 1
    assert written[0].name == "ok.py"


# =============================================================================
# 4. Entry 탐지
# =============================================================================
def _setup_pkg_with_main(workdir: Path, pkg_name: str = "calc") -> tuple[Path, Path]:
    """workdir/src/<pkg>/__init__.py + __main__.py 생성 후 (init, main) 반환."""
    pkg_dir = workdir / "src" / pkg_name
    pkg_dir.mkdir(parents=True)
    init = pkg_dir / "__init__.py"
    init.write_text("")
    main = pkg_dir / "__main__.py"
    main.write_text("print('main')\n")
    return init, main


def test_detect_target_prefers_dunder_main(tmp_path: Path) -> None:
    init, main = _setup_pkg_with_main(tmp_path)
    cli = main.parent / "cli.py"  # 같은 패키지 내부 cli.py
    cli.write_text("print('cli')\n")

    target = _detect_runnable_target(tmp_path, [init, main, cli])

    assert target is not None
    assert target.cmd_args == ["-m", "calc"]
    assert target.cwd == tmp_path / "src"


def test_detect_target_falls_back_to_cli_in_package(tmp_path: Path) -> None:
    """`__main__.py` 가 없으면 `cli.py` 가 패키지 내부일 때 module 로 실행."""
    pkg_dir = tmp_path / "src" / "calc"
    pkg_dir.mkdir(parents=True)
    init = pkg_dir / "__init__.py"
    init.write_text("")
    cli = pkg_dir / "cli.py"
    cli.write_text("print('cli')\n")

    target = _detect_runnable_target(tmp_path, [init, cli])

    assert target is not None
    assert target.cmd_args == ["-m", "calc.cli"]


def test_detect_target_runs_top_level_script_when_no_package(tmp_path: Path) -> None:
    """패키지 없이 cli.py 만 root 에 있으면 그냥 스크립트로 실행."""
    cli = tmp_path / "cli.py"
    cli.write_text("print('script')\n")

    target = _detect_runnable_target(tmp_path, [cli])

    assert target is not None
    assert target.cmd_args == ["cli.py"]
    assert target.cwd == tmp_path


def test_detect_target_returns_none_when_no_runnable(tmp_path: Path) -> None:
    """선호 이름도 없고 `__main__` 블록도 없는 헬퍼만 → None."""
    a = tmp_path / "alpha.py"
    a.write_text("def x(): pass\n")
    b = tmp_path / "bravo.py"
    b.write_text("def y(): pass\n")

    assert _detect_runnable_target(tmp_path, [a, b]) is None


# =============================================================================
# 5. 통합 — 실제 subprocess
# =============================================================================
def _make_pkg_files(tmp_path: Path, files: dict[str, str]) -> list[Path]:
    """입력 dict {relpath: content} 를 평탄화 파일명으로 디스크에 쓴 뒤 list[Path] 반환.

    `# file: <relpath>` 헤더는 자동 prepend.
    """
    out: list[Path] = []
    for relpath, body in files.items():
        flat = relpath.replace("/", "__").replace("\\", "__")
        p = tmp_path / flat
        p.write_text(f"# file: {relpath}\n{body}", encoding="utf-8")
        out.append(p)
    return out


def test_run_package_single_file_pass(tmp_path: Path) -> None:
    """단일 파일 시나리오 — backward compat."""
    files = _make_pkg_files(tmp_path, {"calculator.py": "print('single ok')\n"})
    result = run_python_package_in_sandbox(files, timeout_sec=10)

    assert isinstance(result, SandboxResult)
    assert result.verdict == "PASS"
    assert "single ok" in result.stdout


def test_run_package_multi_file_with_relative_import_pass(tmp_path: Path) -> None:
    """**핵심 증명**: __main__.py + helper.py + 상대 import 가 진짜로 동작."""
    files = _make_pkg_files(
        tmp_path,
        {
            "src/calc/__init__.py": "",
            "src/calc/helper.py": "def add(a, b):\n    return a + b\n",
            "src/calc/__main__.py": (
                "from calc.helper import add\n"
                "print(f'sum={add(2, 3)}')\n"
            ),
        },
    )
    result = run_python_package_in_sandbox(files, timeout_sec=10)

    assert isinstance(result, SandboxResult)
    assert result.verdict == "PASS", f"stderr={result.stderr}"
    assert "sum=5" in result.stdout


def test_run_package_cli_in_package_fallback(tmp_path: Path) -> None:
    """`__main__.py` 없을 때 `cli.py` 가 module 로 실행 (`python -m pkg.cli`)."""
    files = _make_pkg_files(
        tmp_path,
        {
            "calc/__init__.py": "",
            "calc/cli.py": "print('cli entry')\n",
        },
    )
    result = run_python_package_in_sandbox(files, timeout_sec=10)

    assert result is not None
    assert result.verdict == "PASS"
    assert "cli entry" in result.stdout


def test_run_package_returns_none_when_no_entry(tmp_path: Path) -> None:
    """모든 파일이 헬퍼이고 entry 가 없으면 None 반환 (호출 측 skip 신호)."""
    files = _make_pkg_files(
        tmp_path,
        {
            "calc/__init__.py": "",
            "calc/utils.py": "def x(): pass\n",  # entry 후보 아님
        },
    )
    result = run_python_package_in_sandbox(files, timeout_sec=10)

    assert result is None


def test_run_package_captures_traceback_on_fail(tmp_path: Path) -> None:
    """의도적 예외는 FAIL + stderr 에 traceback 인용."""
    files = _make_pkg_files(
        tmp_path,
        {
            "calc/__init__.py": "",
            "calc/__main__.py": "raise RuntimeError('boom')\n",
        },
    )
    result = run_python_package_in_sandbox(files, timeout_sec=10)

    assert result is not None
    assert result.verdict == "FAIL"
    assert "RuntimeError" in result.stderr
    assert "boom" in result.stderr


def test_run_package_validates_inputs() -> None:
    """잘못된 입력은 ValueError/TypeError 즉시 거부."""
    with pytest.raises(TypeError):
        run_python_package_in_sandbox("not a list", timeout_sec=10)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        run_python_package_in_sandbox(["not a path"], timeout_sec=10)  # type: ignore[list-item]
    with pytest.raises(ValueError):
        run_python_package_in_sandbox([], timeout_sec=0)


def test_run_package_empty_list_returns_none() -> None:
    """빈 목록은 ValueError 가 아니라 그냥 None — 호출 측이 자연스럽게 skip."""
    assert run_python_package_in_sandbox([], timeout_sec=10) is None
