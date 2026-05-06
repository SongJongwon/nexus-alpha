# -*- coding: utf-8 -*-
"""Update Checker 실 통합 회귀 방지 테스트 (PR #66).

배경:
    PR #65 까지의 Update Checker 는 *사양 + 참조 구현* 만 산출 (`32_update_module_spec.md`).
    `code/updater.py` 파일은 미산출 → 산출 entry (calculator.py 등) 가 실제로 import
    하지 못함. 다음 우선순위 (10차 E2E 시리즈 종료 후) 가 *Update Checker 실 통합*.

PR #66 처방 (방어선 4 패턴 — deterministic schema-level 보강):
    1. `UpdateModuleSpecOutput.updater_py_reference` description 에 `# file: updater.py`
       헤더 명시 강화
    2. `to_markdown()` 단계에서 ```python``` fence + `# file: updater.py` 헤더 자동 보장
    3. workflow 에서 `update_module_spec` → `_extract_code_blocks` 호출 → `code/updater.py`
       자동 생성
    4. 산출 entry 에 `try: import updater; updater.start()` 라인 자동 삽입 (silent fail)

PR #61 fence 마커 회귀 사례와 같은 LLM 자유 영역 의존을 deterministic 단계로 차단.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# 1. UpdateModuleSpecOutput schema description — # file: updater.py 헤더 명시
# ---------------------------------------------------------------------------


def test_update_module_spec_field_mentions_file_header() -> None:
    """schema field description 에 `# file: updater.py` 헤더 명시 (PR #66)."""
    from src.workflows._schemas import UpdateModuleSpecOutput

    desc = UpdateModuleSpecOutput.model_fields["updater_py_reference"].description
    assert "# file: updater.py" in desc, "updater_py_reference description 에 헤더 명시 누락"
    assert "PR #66" in desc, "PR #66 라벨 누락"
    assert "_extract_code_blocks" in desc, "추출 메커니즘 명시 누락"


# ---------------------------------------------------------------------------
# 2. _ensure_file_header_in_python_block 헬퍼
# ---------------------------------------------------------------------------


def test_ensure_file_header_inserts_when_missing() -> None:
    """첫 ```python``` 블록 첫 줄에 # file: 헤더 부재 시 자동 삽입."""
    from src.workflows._schemas import _ensure_file_header_in_python_block

    md = "```python\nimport requests\ndef start(): pass\n```"
    out = _ensure_file_header_in_python_block(md, "updater.py")
    assert "# file: updater.py" in out
    # 헤더는 fence 직후, 원본 코드보다 먼저
    assert out.index("# file: updater.py") < out.index("import requests")


def test_ensure_file_header_idempotent_when_present() -> None:
    """헤더 이미 있으면 그대로 (LLM 결정 존중 — idempotent)."""
    from src.workflows._schemas import _ensure_file_header_in_python_block

    md = "```python\n# file: updater.py\nimport requests\n```"
    out = _ensure_file_header_in_python_block(md, "updater.py")
    # 헤더 정확히 1회만
    assert out.count("# file: updater.py") == 1


def test_ensure_file_header_respects_existing_other_filename() -> None:
    """LLM 이 다른 파일명을 명시했다면 (예: my_updater.py) 그대로 — 덮어쓰지 않음."""
    from src.workflows._schemas import _ensure_file_header_in_python_block

    md = "```python\n# file: my_updater.py\nimport requests\n```"
    out = _ensure_file_header_in_python_block(md, "updater.py")
    assert "# file: my_updater.py" in out
    # updater.py 헤더는 추가되지 않음 (이미 다른 파일명 명시됨)
    assert "# file: updater.py" not in out


def test_ensure_file_header_skips_when_no_python_fence() -> None:
    """fence 없으면 그대로 — _ensure_python_fence 가 먼저 처리해야 함 (분리 책임)."""
    from src.workflows._schemas import _ensure_file_header_in_python_block

    md = "raw code without fence\nimport x"
    out = _ensure_file_header_in_python_block(md, "updater.py")
    assert out == md  # 변경 없음


def test_ensure_file_header_handles_empty_string() -> None:
    """빈 입력 — defensive."""
    from src.workflows._schemas import _ensure_file_header_in_python_block

    assert _ensure_file_header_in_python_block("", "updater.py") == ""


# ---------------------------------------------------------------------------
# 3. UpdateModuleSpecOutput.to_markdown() 자동 보강
# ---------------------------------------------------------------------------


def test_to_markdown_auto_wraps_raw_updater_code() -> None:
    """fence + 헤더 모두 누락한 raw 코드 → fence + 헤더 자동 보강 (PR #66)."""
    from src.workflows._schemas import UpdateModuleSpecOutput

    raw_code = (
        "import requests\n"
        "def start():\n"
        "    print('check')\n"
    )
    m = UpdateModuleSpecOutput(
        summary="x",
        module_design="x",
        updater_py_reference=raw_code,  # fence 없음, 헤더 없음
        gui_integration="x",
        security_checklist="x",
        author_notes="x",
    )
    md = m.to_markdown()
    # fence 자동 감싸기 (PR #64) + 헤더 자동 삽입 (PR #66)
    assert "```python" in md
    assert "# file: updater.py" in md
    # 원본 코드 보존
    assert "import requests" in md


def test_to_markdown_preserves_existing_fence_and_header() -> None:
    """fence + 헤더 모두 있으면 그대로 (idempotent)."""
    from src.workflows._schemas import UpdateModuleSpecOutput

    fenced = (
        "```python\n"
        "# file: updater.py\n"
        "import requests\n"
        "def start(): pass\n"
        "```"
    )
    m = UpdateModuleSpecOutput(
        summary="x",
        module_design="x",
        updater_py_reference=fenced,
        gui_integration="x",
        security_checklist="x",
        author_notes="x",
    )
    md = m.to_markdown()
    # ```python 정확히 1회 (두 번 감싸지 않음)
    assert md.count("```python") == 1
    # # file: updater.py 정확히 1회
    assert md.count("# file: updater.py") == 1


# ---------------------------------------------------------------------------
# 4. _ensure_updater_import_in_entry — entry 자동 import 삽입
# ---------------------------------------------------------------------------


def test_ensure_updater_import_injects_into_entry(tmp_path: Path) -> None:
    """code_dir 에 updater.py + calculator.py 가 있으면 calculator.py 에 import 라인 삽입."""
    from src.workflows.analyze_and_implement import (
        _UPDATER_AUTOINJECT_MARKER,
        _ensure_updater_import_in_entry,
    )

    code_dir = tmp_path / "code"
    code_dir.mkdir()
    updater = code_dir / "updater.py"
    updater.write_text("def start(): pass\n", encoding="utf-8")
    calculator = code_dir / "calculator.py"
    calculator.write_text("# original\nclass App: pass\n", encoding="utf-8")

    modified = _ensure_updater_import_in_entry(code_dir, [updater, calculator])

    assert calculator in modified
    content = calculator.read_text(encoding="utf-8")
    assert _UPDATER_AUTOINJECT_MARKER in content
    assert "import updater" in content
    assert "updater.start()" in content
    # 원본 보존
    assert "# original" in content
    assert "class App: pass" in content


def test_ensure_updater_import_skips_when_no_updater_py(tmp_path: Path) -> None:
    """updater.py 가 추출 목록에 없으면 아무것도 안 함."""
    from src.workflows.analyze_and_implement import _ensure_updater_import_in_entry

    code_dir = tmp_path / "code"
    code_dir.mkdir()
    calculator = code_dir / "calculator.py"
    calculator.write_text("# original\n", encoding="utf-8")

    modified = _ensure_updater_import_in_entry(code_dir, [calculator])

    assert modified == []
    # calculator.py 변경 없음
    assert calculator.read_text(encoding="utf-8") == "# original\n"


def test_ensure_updater_import_skips_test_files(tmp_path: Path) -> None:
    """test_*.py 는 entry 후보에서 제외 — pytest 가 import 시도해서 깨질 수 있음."""
    from src.workflows.analyze_and_implement import (
        _UPDATER_AUTOINJECT_MARKER,
        _ensure_updater_import_in_entry,
    )

    code_dir = tmp_path / "code"
    code_dir.mkdir()
    updater = code_dir / "updater.py"
    updater.write_text("def start(): pass\n", encoding="utf-8")
    test_file = code_dir / "test_calculator.py"
    test_file.write_text("def test_x(): assert 1 == 1\n", encoding="utf-8")

    modified = _ensure_updater_import_in_entry(code_dir, [updater, test_file])

    # test_*.py 는 수정 대상 아님
    assert modified == []
    assert _UPDATER_AUTOINJECT_MARKER not in test_file.read_text(encoding="utf-8")


def test_ensure_updater_import_idempotent(tmp_path: Path) -> None:
    """두 번 호출해도 import 라인은 한 번만 추가 (idempotent)."""
    from src.workflows.analyze_and_implement import _ensure_updater_import_in_entry

    code_dir = tmp_path / "code"
    code_dir.mkdir()
    updater = code_dir / "updater.py"
    updater.write_text("def start(): pass\n", encoding="utf-8")
    calculator = code_dir / "calculator.py"
    calculator.write_text("# original\n", encoding="utf-8")

    _ensure_updater_import_in_entry(code_dir, [updater, calculator])
    second = _ensure_updater_import_in_entry(code_dir, [updater, calculator])

    assert second == []  # 두 번째는 변경 없음
    content = calculator.read_text(encoding="utf-8")
    # import updater 정확히 1회 (중복 삽입 없음)
    assert content.count("import updater") == 1


def test_ensure_updater_import_skips_updater_itself(tmp_path: Path) -> None:
    """updater.py 자기 자신은 entry 후보에서 제외 — 자기 import 무한 loop 방지."""
    from src.workflows.analyze_and_implement import _ensure_updater_import_in_entry

    code_dir = tmp_path / "code"
    code_dir.mkdir()
    updater = code_dir / "updater.py"
    original = "def start(): pass\n"
    updater.write_text(original, encoding="utf-8")

    _ensure_updater_import_in_entry(code_dir, [updater])

    # updater.py 자체에는 자동 주입 안 됨
    assert updater.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 5. _integrate_update_checker — workflow level 통합 helper
# ---------------------------------------------------------------------------


def test_integrate_update_checker_extracts_and_injects(tmp_path: Path) -> None:
    """update_module_spec 본문 → code/updater.py 추출 + entry 자동 import."""
    from src.workflows.analyze_and_implement import _integrate_update_checker

    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()
    code_dir = workflow_dir / "code"
    code_dir.mkdir()
    # entry 미리 존재 (GUI Code Generator 산출 시뮬레이션)
    calculator = code_dir / "calculator.py"
    calculator.write_text("# entry\nclass App: pass\n", encoding="utf-8")

    update_module_spec = (
        "summary line\n\n"
        "### 2. updater.py 참조 구현\n\n"
        "```python\n"
        "# file: updater.py\n"
        "def start():\n"
        "    print('checking updates')\n"
        "```\n"
    )

    integrated = _integrate_update_checker(workflow_dir, update_module_spec)

    # code/updater.py 생성됨
    updater = code_dir / "updater.py"
    assert updater.exists()
    assert "def start" in updater.read_text(encoding="utf-8")
    # calculator.py 에 import 라인 주입됨
    cal_content = calculator.read_text(encoding="utf-8")
    assert "import updater" in cal_content
    assert "updater.start()" in cal_content
    # 반환 목록에 둘 다 있음
    paths = {p.name for p in integrated}
    assert "updater.py" in paths
    assert "calculator.py" in paths


def test_integrate_update_checker_handles_empty_spec(tmp_path: Path) -> None:
    """빈 update_module_spec → 빈 리스트, 부작용 없음."""
    from src.workflows.analyze_and_implement import _integrate_update_checker

    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()

    integrated = _integrate_update_checker(workflow_dir, "")

    assert integrated == []
    # code/ 도 생성 안 됨
    assert not (workflow_dir / "code").exists()


def test_integrate_update_checker_handles_spec_without_python_block(
    tmp_path: Path,
) -> None:
    """fence 마커 없는 spec → updater.py 미산출, 부작용 없음."""
    from src.workflows.analyze_and_implement import _integrate_update_checker

    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()
    code_dir = workflow_dir / "code"
    code_dir.mkdir()
    calculator = code_dir / "calculator.py"
    calculator.write_text("# entry\n", encoding="utf-8")

    spec_no_python = "# 모듈 설계\n없음\n"  # python 블록 없음
    integrated = _integrate_update_checker(workflow_dir, spec_no_python)

    assert integrated == []
    # calculator.py 변경 없음
    assert calculator.read_text(encoding="utf-8") == "# entry\n"


# ---------------------------------------------------------------------------
# 6. Update Checker backstory — # file: updater.py 헤더 명시
# ---------------------------------------------------------------------------


def test_update_checker_backstory_mentions_file_header_for_updater() -> None:
    """backstory 에 `# file: updater.py` 헤더 강제 + PR #66 라벨 명시."""
    from src.agents.build_release.update_checker import UPDATE_CHECKER_BACKSTORY

    assert "# file: updater.py" in UPDATE_CHECKER_BACKSTORY
    assert "PR #66" in UPDATE_CHECKER_BACKSTORY or "_extract_code_blocks" in UPDATE_CHECKER_BACKSTORY


def test_update_checker_backstory_avoids_pkg_prefix() -> None:
    """backstory 에 `<pkg>/updater.py` 같은 경로 prefix 가 없어야 (PR #66 단순화).
    이 prefix 가 있으면 _extract_code_blocks 가 `<pkg>__updater.py` 로 떨어져
    import 가 깨짐."""
    from src.agents.build_release.update_checker import UPDATE_CHECKER_BACKSTORY

    # pkg/ prefix 명시 금지 신호
    assert "<pkg>/" not in UPDATE_CHECKER_BACKSTORY or "접두사 금지" in UPDATE_CHECKER_BACKSTORY


# ---------------------------------------------------------------------------
# 7. workflow 통합 source-level grep
# ---------------------------------------------------------------------------

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1] / "workflows" / "analyze_and_implement.py"
)


def test_workflow_calls_integrate_update_checker() -> None:
    """analyze_and_implement.py 가 _integrate_update_checker 호출 (release 분기 안)."""
    src = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "_integrate_update_checker(" in src
    # release branch 안에서 호출 — release_decision 머지 직후
    assert "release_result.update_module_spec" in src


def test_workflow_defines_updater_autoinject_marker() -> None:
    """안정적 마커 문자열 정의 — idempotent 검증 키."""
    src = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "_UPDATER_AUTOINJECT_MARKER" in src
    assert "Auto-injected by Nexus Alpha PR #66" in src
