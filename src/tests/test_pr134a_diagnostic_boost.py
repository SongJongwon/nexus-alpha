# -*- coding: utf-8 -*-
"""install.ps1 진단 보강 정적 검증 (PR #134-A).

배경 (친구 PC 라이브 검증, 2026-05-14, PR #133 머지 후):
    "로컬 Python 설치 완료했으나 tkinter import 실패 / output= / exit=1" 발생.
    안내문구는 ``Include_tcltk=1 무시됨`` 으로 추정했으나 실제로는 진단 데이터 0.
    근본 원인: ``Invoke-NativeSafely`` 가 ``2>$null`` 로 stderr 폐기 (PR #126
    NativeCommandError 차단 의도가 *폐기* 로 잘못 구현). 친구 PC 의 ``output=`` 빈
    stdout 은 ``import tkinter`` 가 stderr 로 ``ModuleNotFoundError`` 를 뿜었지만
    우리가 못 본 결과물.

PR #134-A 처방 (자동 복구 0, 진단만):
    1. ``Invoke-NativeSafely`` 에 ``StdErr`` 필드 추가 (file-handle 레벨 redirect →
       NativeCommandError 미발생 보장 유지). 기존 caller 영향 0.
    2. ``Get-TkinterDiagnostics`` 신규 — 실패 시 _tkinter C 확장 직접 import,
       파일 probe (DLLs/_tkinter.pyd, tcl/, Lib/tkinter/), 인스톨러 로그 tail,
       silent install 명령 echo 모두 dump.
    3. silent install 호출 직전 정확한 명령을 화면에 echo + ``$script:LAST_INSTALL_CMD``
       에 저장 → diagnostics dump 에 포함.

본 테스트가 깨지면 진단 회귀 — 친구 PC / IT 부서 / LLM 이 원인 단정 불가.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_PS1_PATH = PROJECT_ROOT / "install.ps1"


def _read_install_ps1() -> str:
    return INSTALL_PS1_PATH.read_text(encoding="utf-8")


def _extract_function(text: str, name: str) -> str:
    """``function <name> { ... }`` 본문 추출 (중괄호 균형 매칭)."""
    pattern = rf"function\s+{re.escape(name)}\s*\{{"
    m = re.search(pattern, text)
    assert m is not None, f"function {name} 정의 누락"
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"function {name} 의 닫는 중괄호 매칭 실패"
    return text[start : i - 1]


# ---------------------------------------------------------------------------
# 1. Invoke-NativeSafely — stderr 캡처
# ---------------------------------------------------------------------------


def test_invoke_native_safely_captures_stderr_not_discards() -> None:
    """``Invoke-NativeSafely`` 가 stderr 를 캡처해야 한다 (폐기 X).

    회귀 차단 — ``2>$null`` 패턴이 다시 들어오면 친구 PC 와 동일한
    "output= / exit=1 / 원인 불명" 시나리오 재발.
    """
    body = _extract_function(_read_install_ps1(), "Invoke-NativeSafely")
    # 주석 라인 제거 (역사적 설명에 ``2>$null`` 가 등장하는 것은 OK,
    # 실 코드에 잔존하는 것만 회귀로 간주)
    code_lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    # stderr 를 file-handle 로 redirect (폐기가 아닌 캡처)
    assert "2>$stderrFile" in code, (
        "stderr 캡처 누락 — '2>$stderrFile' 패턴이 사라졌거나 변경됨"
    )
    # 기존 폐기 패턴 잔존 없음 (실 코드 한정)
    assert "2>$null" not in code, (
        "stderr 폐기 패턴 '2>$null' 가 실 코드에 회귀 — PR #134-A fix 무력화"
    )
    # 임시 파일 cleanup 보장
    assert "Remove-Item" in code and "stderrFile" in code, (
        "stderr 임시 파일 cleanup 누락 — TEMP 누적 위험"
    )


def test_invoke_native_safely_returns_stderr_field() -> None:
    """반환 객체에 ``StdErr`` 필드가 있어야 한다 (caller 가 .StdErr 접근 가능)."""
    body = _extract_function(_read_install_ps1(), "Invoke-NativeSafely")
    # pscustomobject 안에 StdErr = ... 패턴
    assert re.search(r"StdErr\s*=", body), "StdErr 필드 정의 누락"
    # StdErr 도 Trim() 처리 (StdOut 와 일관성)
    assert "$stderr.Trim()" in body, "StdErr Trim() 누락 — 줄바꿈 잔존 위험"


def test_invoke_native_safely_preserves_existing_fields() -> None:
    """기존 caller 호환 — StdOut / ExitCode / Succeeded 필드 유지.

    회귀 차단 — 구조 변경으로 200+ 호출 사이트가 깨지면 안 됨.
    """
    body = _extract_function(_read_install_ps1(), "Invoke-NativeSafely")
    assert re.search(r"StdOut\s*=", body), "StdOut 필드 회귀"
    assert re.search(r"ExitCode\s*=", body), "ExitCode 필드 회귀"
    assert re.search(r"Succeeded\s*=", body), "Succeeded 필드 회귀"


def test_invoke_native_safely_preserves_eap_isolation() -> None:
    """PR #126 의 EAP 격리 (외부 Stop → 내부 Continue) 유지.

    회귀 차단 — EAP 격리 빠지면 stderr 캡처해도 NativeCommandError 가
    함수 호출자를 throw → 외부 try/catch 없으면 install.ps1 abort.
    """
    body = _extract_function(_read_install_ps1(), "Invoke-NativeSafely")
    assert "$savedEAP = $ErrorActionPreference" in body, (
        "PR #126 EAP 격리 회귀 — savedEAP 백업 누락"
    )
    assert "$ErrorActionPreference = 'Continue'" in body, (
        "PR #126 EAP 격리 회귀 — Continue 강제 누락"
    )
    assert "$ErrorActionPreference = $savedEAP" in body, (
        "PR #126 EAP 격리 회귀 — finally 복원 누락"
    )


# ---------------------------------------------------------------------------
# 2. Get-TkinterDiagnostics — 진단 dump 함수
# ---------------------------------------------------------------------------


def test_get_tkinter_diagnostics_function_exists() -> None:
    """``Get-TkinterDiagnostics`` helper 함수 정의."""
    text = _read_install_ps1()
    assert "function Get-TkinterDiagnostics" in text, (
        "PR #134-A 진단 helper 정의 누락"
    )


def test_diagnostics_includes_tk_result_stderr() -> None:
    """[1] tkinter import 결과의 StdErr 를 포함해야 한다.

    이게 친구 PC 시나리오의 *핵심 missing 정보*. ModuleNotFoundError /
    ImportError 메시지가 여기에 나와야 사람이 원인 단정 가능.
    """
    body = _extract_function(_read_install_ps1(), "Get-TkinterDiagnostics")
    # TkResult.StdErr 참조
    assert "TkResult.StdErr" in body or "$TkResult.StdErr" in body, (
        "진단 dump 가 tkinter import 의 StdErr 미포함 — 친구 PC 결함 재발"
    )


def test_diagnostics_probes_underscore_tkinter_c_extension() -> None:
    """[2] _tkinter (C 확장) 직접 import 시도.

    Python wrapper (Lib\\tkinter\\__init__.py) 와 C ext (DLLs\\_tkinter.pyd) 분리 진단.
    wrapper 만 있고 C ext 없는 / C ext 만 있고 wrapper 없는 케이스 구별.
    """
    body = _extract_function(_read_install_ps1(), "Get-TkinterDiagnostics")
    assert "import _tkinter" in body, (
        "_tkinter (C 확장) 직접 import 진단 누락"
    )


def test_diagnostics_probes_filesystem_for_tkinter_components() -> None:
    """[4] 파일시스템 probe — Tcl/Tk 컴포넌트 디스크 존재 여부."""
    body = _extract_function(_read_install_ps1(), "Get-TkinterDiagnostics")
    # 핵심 probe 대상 (✓/✗ 표시)
    assert "_tkinter.pyd" in body, "DLLs\\_tkinter.pyd probe 누락"
    assert "tcl86t.dll" in body or "tcl" in body.lower(), "Tcl 런타임 probe 누락"
    assert "Lib\\tkinter" in body or "tkinter\\__init__.py" in body, (
        "Lib\\tkinter\\__init__.py probe 누락"
    )
    # ✓ / ✗ 마커
    assert "✓" in body and "✗" in body, "✓/✗ probe 마커 누락"


def test_diagnostics_includes_installer_log_tail() -> None:
    """[6] 인스톨러 로그 마지막 N 줄 — silent fail 시 Burn bundle 의사결정 추적."""
    body = _extract_function(_read_install_ps1(), "Get-TkinterDiagnostics")
    assert "Get-Content" in body and "-Tail" in body, (
        "인스톨러 로그 tail 출력 누락"
    )


def test_diagnostics_references_last_install_cmd() -> None:
    """[5] silent install 명령 echo 참조."""
    body = _extract_function(_read_install_ps1(), "Get-TkinterDiagnostics")
    assert "LAST_INSTALL_CMD" in body, (
        "silent install 명령 echo 미참조 — 어떤 옵션이 들어갔는지 dump 불가"
    )


# ---------------------------------------------------------------------------
# 3. Silent install 명령 echo
# ---------------------------------------------------------------------------


def test_install_ps1_records_silent_install_command() -> None:
    """``$script:LAST_INSTALL_CMD`` 에 silent install 명령 저장.

    Get-TkinterDiagnostics 가 dump 시 이 변수를 읽음 → "어떤 옵션이 실제로
    들어갔는가" 를 사용자 / IT 부서가 확인 가능.
    """
    text = _read_install_ps1()
    # 최소 2회 (1차 install + retry) 기록
    occurrences = len(re.findall(r"\$script:LAST_INSTALL_CMD\s*=", text))
    assert occurrences >= 2, (
        f"LAST_INSTALL_CMD 기록 위치가 부족함 ({occurrences}회) — "
        f"1차 install + retry 두 경로 모두 echo 해야 함"
    )


def test_install_ps1_echoes_silent_install_command_to_screen() -> None:
    """silent install 명령을 화면에도 echo (사용자 즉시 확인)."""
    text = _read_install_ps1()
    # "silent install:" 또는 "silent install (retry):" 패턴
    assert "silent install:" in text, "1차 silent install echo 누락"
    assert "silent install (retry):" in text, "retry silent install echo 누락"


# ---------------------------------------------------------------------------
# 4. tkinter 검증 실패 지점 ↔ 진단 dump 통합
# ---------------------------------------------------------------------------


def test_tkinter_validation_failure_calls_diagnostics() -> None:
    """tkinter import 실패 시 ``Get-TkinterDiagnostics`` 자동 호출.

    회귀 차단 — 호출 빠지면 친구 PC 와 동일한 "원인 불명" 안내 재발.
    """
    text = _read_install_ps1()
    # Get-TkinterDiagnostics 호출이 *2회 이상* 등장 — 함수 정의 1회 + tkinter
    # 검증 실패 지점 호출 1회 (함수 정의 자기참조는 1회만이어야 함).
    # 단순 substring count 로 호출 존재 검증.
    occurrences = text.count("Get-TkinterDiagnostics")
    assert occurrences >= 2, (
        f"Get-TkinterDiagnostics 호출 누락 ({occurrences}회 등장) — "
        f"정의 + 호출 합쳐 최소 2회 필요"
    )
    # tkinter 검증 실패 ``Fail @"..."@`` 블록 추출 (Fail 호출 직후 here-string).
    # 주석에 동일 문구가 들어있어도 안 잡히도록 ``Fail @"`` prefix 강제.
    fail_block_match = re.search(
        r'Fail\s+@"\s*\n로컬 Python 설치 완료했으나 tkinter import 실패.*?"@',
        text,
        re.DOTALL,
    )
    assert fail_block_match is not None, (
        "tkinter 검증 실패 ``Fail @\"...\"@`` 블록 추출 실패"
    )
    fail_block = fail_block_match.group(0)
    assert "$diag" in fail_block, (
        "tkinter Fail 메시지에 $diag (진단 dump) 변수 보간 누락"
    )


def test_tkinter_validation_failure_drops_misleading_inclusion_message() -> None:
    """과거 안내문구 ``Include_tcltk=1 무시됨`` 의 *추측 단정* 톤 제거.

    배경: PR #133 의 Fail 메시지가 "원인: 인스톨러가 Tcl/Tk 컴포넌트 미포함" 이라고
    *단정* 했으나 친구 PC 진단 후 다른 원인일 수도 있다고 판명. PR #134-A 는
    진단 dump 를 보여주고 사용자가 원인을 *읽고 단정* 하도록 변경.
    """
    text = _read_install_ps1()
    # 과거의 단정 안내 ("원인: ... 미포함 (Include_tcltk=1 무시됨)") 가 *그대로* 남아있으면 안 됨
    # — 새 안내는 진단 [4] 의 ✗ 표시를 보고 사용자가 판단하도록 유도
    assert "위 진단" in text, (
        "새 안내 ('위 진단 [4] 의 ✗ 표시된 파일이 무엇인지 확인') 누락"
    )


# ---------------------------------------------------------------------------
# 5. 신규 helper 가 함수 순서 / 호출 가능성 보장
# ---------------------------------------------------------------------------


def test_get_tkinter_diagnostics_defined_before_install_local_python() -> None:
    """``Get-TkinterDiagnostics`` 가 ``Install-LocalPython313`` 보다 *앞* 에 정의.

    PowerShell 은 함수 정의 순서에 민감 — 호출 시점에 정의 안 된 함수면
    CommandNotFoundException. install.ps1 은 dot-source 가 아니라 단일 스크립트
    실행이므로 forward declaration 불가.
    """
    text = _read_install_ps1()
    diag_pos = text.find("function Get-TkinterDiagnostics")
    install_pos = text.find("function Install-LocalPython313")
    assert diag_pos > 0, "Get-TkinterDiagnostics 정의 누락"
    assert install_pos > 0, "Install-LocalPython313 정의 누락"
    assert diag_pos < install_pos, (
        f"Get-TkinterDiagnostics ({diag_pos}) 가 Install-LocalPython313 "
        f"({install_pos}) 보다 뒤에 정의됨 — CommandNotFoundException 위험"
    )
