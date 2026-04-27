# -*- coding: utf-8 -*-
"""
Nexus Alpha Platform Tester (빌드 & 배포 본부, Phase 4.5 / v4 — 5/5 마지막).

본 모듈은 두 가지를 함께 제공한다 (Sandbox Runner 와 같은 패턴 — 결정론 +
Agent 하이브리드):

1. **`test_executable_in_sandbox(exe_path, ...)` 함수**
       LLM 과 무관한 결정론적 검증자. Build Engineer/Installer Creator 가 만든
       실행 파일(.exe / .AppImage / native binary)을 별도 프로세스로 spawn 하고,
       exit_code · startup_time · stdout/stderr · started_successfully · timed_out
       을 `PlatformTestResult` 데이터클래스로 반환한다. verdict 는 다음 4종 중
       하나로 자동 분류:
           - PASS    : 정상 종료 (exit_code == 0) 또는 timeout 까지 살아 있음 (GUI)
           - CRASH   : 빠르게 비정상 종료 (exit_code != 0, 1초 이내)
           - FAIL    : 비정상 종료 (exit_code != 0)
           - TIMEOUT : 타임아웃 도달 (살아 있었지만 강제 종료)

2. **`create_platform_tester_agent()` 팩토리**
       위 함수가 산출한 `PlatformTestResult` 를 *해석·보고* 하는 CrewAI Agent.
       PASS/FAIL/CRASH/TIMEOUT 분류를 신뢰하고 뒤집지 않으며, 측정값을 사람이
       읽을 수 있는 한국어 보고서로 변환한다 (Sandbox Runner Agent 와 같은 원칙).

조직도 정합:
    `nexus_alpha_org_v4.md` §3-8 — 빌드 & 배포 본부 9명 중 1명 (Phase 4.5 의
    마지막 5번째). Phase 4.5 사슬 (Dependency Analyzer → Build Engineer → Asset
    Manager → Installer Creator → **Platform Tester**) 의 종착지.

⚠️  보안·격리 한계 — Sandbox Runner 와 동일:
    - `subprocess` + `timeout` 만으로는 OS 레벨 격리가 없다. 실행되는 .exe 는
      호스트의 파일/네트워크/환경변수에 모두 접근 가능. 신뢰할 수 없는 산출물은
      실행하지 말 것.
    - 진짜 격리(**Windows Sandbox CLI**, Docker, 가상머신, seccomp, firejail)는
      별도 외부 도구 의존이라 본 모듈에 통합하지 않음. 격리 구성·호출은 별도
      후속 작업 (v5 또는 Phase 4.5 보강).

GUI 자동화 한계:
    실제 GUI 윈도우 자동 클릭·검증(UI Automation API, AppleScript, AT-SPI)은 OS
    의존성이 매우 커서 별도 작업으로 분리. 본 모듈은 *프로세스가 spawn 후 N초간
    크래시 없이 살아 있는가* 정도의 *기본 부팅 smoke* 만 검증한다 — 그것만으로도
    'PyInstaller 빌드는 통과했지만 더블클릭하면 즉시 죽는' 흔한 회귀를 잡아낼 수 있다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from crewai import Agent

from src.llm import NexusAlphaLLM


# ---------------------------------------------------------------------------
# 결과 데이터클래스
# ---------------------------------------------------------------------------
@dataclass
class PlatformTestResult:
    """`test_executable_in_sandbox` 의 구조화 산출물.

    Attributes:
        exit_code: 자식 프로세스 종료 코드. 정상 종료 0. 타임아웃 강제 종료 시 -1.
        stdout: 표준 출력 (UTF-8 디코딩, errors=replace).
        stderr: 표준 오류.
        startup_time_sec: 프로세스 spawn → 첫 stdout 또는 process.poll() 첫 변화
            까지 측정한 *체감 부팅 시간*. 정확치는 아니지만 회귀 추적엔 충분.
        elapsed_sec: 전체 경과 시간 (정상 종료 또는 타임아웃까지).
        timed_out: 타임아웃으로 강제 종료됐는지 여부.
        timeout_sec: 호출 시 사용된 타임아웃 임계값(초).
        started_successfully: spawn 후 0.5초 동안 살아 있었으면 True.
            CLI 앱은 정상 종료가 0.5초 이내일 수 있어 elapsed_sec 와 함께 봐야 함.
        verdict: PASS / FAIL / CRASH / TIMEOUT 중 하나로 자동 분류.
            - PASS    : exit_code == 0 (정상 종료) OR (timed_out AND startup_time>0)
                        (GUI 처럼 영원히 살아 있는 케이스 → timeout 도 정상 신호)
            - CRASH   : exit_code != 0 AND elapsed_sec < 1.0
                        (즉시 죽음 — 가장 흔한 빌드 회귀 패턴)
            - FAIL    : exit_code != 0 AND elapsed_sec >= 1.0 (실행 후 비정상 종료)
            - TIMEOUT : timed_out AND startup_time == 0 (부팅조차 못 함)
        exe_path: 검증된 실행 파일 절대 경로 (보고용).
    """

    exit_code: int
    stdout: str
    stderr: str
    startup_time_sec: float
    elapsed_sec: float
    timed_out: bool
    timeout_sec: int
    started_successfully: bool
    exe_path: Optional[Path]
    verdict: str = field(init=False)

    def __post_init__(self) -> None:
        if self.timed_out:
            # 타임아웃 — 부팅했으면 PASS (GUI), 부팅 못 했으면 TIMEOUT
            self.verdict = "PASS" if self.started_successfully else "TIMEOUT"
        elif self.exit_code == 0:
            self.verdict = "PASS"
        elif self.elapsed_sec < 1.0:
            self.verdict = "CRASH"  # 즉시 죽음 — 가장 큰 위험 신호
        else:
            self.verdict = "FAIL"


# ---------------------------------------------------------------------------
# 결정론 검증자 (LLM 무관)
# ---------------------------------------------------------------------------
# 부팅 성공 판정 임계 — spawn 후 이만큼 살아 있으면 started_successfully=True.
# 너무 짧으면 CLI 앱이 부팅 실패로 잘못 분류, 너무 길면 GUI 부팅 자체가 늦어 보임.
_STARTUP_PROBE_SEC: float = 0.5


def test_executable_in_sandbox(
    exe_path: Path,
    *,
    timeout_sec: int = 30,
    args: Optional[list[str]] = None,
    extra_env: Optional[dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> PlatformTestResult:
    """실행 파일을 별도 프로세스로 spawn 해 부팅·실행 결과를 측정한다.

    동작 절차:
        1. 입력 검증 (파일 존재 + 양수 timeout)
        2. 임시 디렉터리(또는 호출 측 cwd) 에서 subprocess.Popen
        3. 0.5초 후 살아 있는지 검사 → started_successfully 결정
        4. 타임아웃까지 wait. 정상 종료면 exit_code, 타임아웃이면 강제 종료
        5. stdout/stderr 캡처 + 경과 시간 측정
        6. PlatformTestResult 반환 (verdict 자동 분류)

    Args:
        exe_path: 검증할 실행 파일의 절대 경로 (.exe / .AppImage / native binary
            / shebang 스크립트 등).
        timeout_sec: 자식 프로세스 강제 종료 임계 (양수). 기본 30초.
            GUI 앱은 timeout 까지 살아 있는 게 정상이므로 PASS 로 분류됨.
        args: 실행 파일에 전달할 인자. None 이면 빈 리스트.
        extra_env: 자식 프로세스에 주입할 추가 환경변수. 부모 환경에 덮어쓴다.
        cwd: 실행 디렉터리. None 이면 임시 tmpdir 자동 생성·정리.

    Returns:
        구조화된 `PlatformTestResult`.

    Raises:
        FileNotFoundError: exe_path 가 존재하지 않을 때.
        ValueError: timeout_sec ≤ 0.
        TypeError: exe_path 가 Path 가 아닐 때.

    보안 경고 (모듈 docstring 참조):
        본 함수는 진짜 격리가 아님. 신뢰할 수 없는 .exe 실행 금지.
    """
    if not isinstance(exe_path, Path):
        raise TypeError(f"exe_path must be Path, got {type(exe_path).__name__}")
    if not exe_path.exists():
        raise FileNotFoundError(f"executable not found: {exe_path}")
    if timeout_sec <= 0:
        raise ValueError(f"timeout_sec must be positive, got {timeout_sec}")

    cmd: list[str] = [str(exe_path), *(args or [])]
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}

    # 사용자 지정 cwd 가 없으면 안전한 tmpdir 자동 생성
    auto_tmpdir: Optional[tempfile.TemporaryDirectory] = None
    if cwd is None:
        auto_tmpdir = tempfile.TemporaryDirectory(prefix="nexus_platform_test_")
        run_cwd = Path(auto_tmpdir.name)
    else:
        run_cwd = cwd

    start = time.monotonic()
    startup_time = 0.0
    timed_out = False
    started_ok = False
    stdout_text = ""
    stderr_text = ""
    exit_code = -1

    try:
        proc = subprocess.Popen(  # noqa: S603 (의도적 subprocess 호출)
            cmd,
            cwd=str(run_cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        # 단계 1: 부팅 성공 여부 — 0.5초 살아 있으면 OK
        try:
            proc.wait(timeout=_STARTUP_PROBE_SEC)
            # 0.5초 안에 종료 — CLI 앱일 수도, 즉시 크래시일 수도. 분류는 verdict 가.
            startup_time = time.monotonic() - start
            started_ok = (proc.returncode == 0)  # 0 종료면 정상 부팅 후 종료
        except subprocess.TimeoutExpired:
            startup_time = _STARTUP_PROBE_SEC
            started_ok = True  # 0.5초간 살아 있었음 → 부팅 성공

        # 단계 2: 남은 시간 동안 wait (이미 죽었으면 즉시 통과)
        remaining = max(0.0, timeout_sec - (time.monotonic() - start))
        try:
            stdout_text, stderr_text = proc.communicate(timeout=remaining if remaining > 0 else 0.1)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                stdout_text, stderr_text = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                stdout_text, stderr_text = "", ""
            exit_code = -1
    finally:
        elapsed = time.monotonic() - start
        if auto_tmpdir is not None:
            try:
                auto_tmpdir.cleanup()
            except OSError:
                # tmpdir 정리 실패는 non-fatal — Windows 에서 아직 핸들이 남아있을 수 있음
                pass

    return PlatformTestResult(
        exit_code=exit_code,
        stdout=stdout_text or "",
        stderr=stderr_text or "",
        startup_time_sec=round(startup_time, 3),
        elapsed_sec=round(elapsed, 3),
        timed_out=timed_out,
        timeout_sec=timeout_sec,
        started_successfully=started_ok,
        exe_path=exe_path,
    )


# ---------------------------------------------------------------------------
# Agent 직렬화 헬퍼
# ---------------------------------------------------------------------------
def format_platform_test_result_for_task(
    result: PlatformTestResult,
    *,
    max_lines: int = 20,
) -> str:
    """`PlatformTestResult` 를 Agent Task description 본문으로 직렬화.

    너무 긴 stdout/stderr 는 마지막 `max_lines` 줄로 자른다 (Agent 토큰 예산 보호).
    """

    def _tail(text: str) -> str:
        if not text:
            return "(empty)"
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text.rstrip()
        return "... (앞부분 생략) ...\n" + "\n".join(lines[-max_lines:])

    return (
        f"verdict: {result.verdict}\n"
        f"exit_code: {result.exit_code}\n"
        f"startup_time_sec: {result.startup_time_sec}\n"
        f"elapsed_sec: {result.elapsed_sec}\n"
        f"timeout_sec: {result.timeout_sec}\n"
        f"timed_out: {result.timed_out}\n"
        f"started_successfully: {result.started_successfully}\n"
        f"exe_path: {result.exe_path}\n"
        f"--- stdout (마지막 {max_lines}줄) ---\n{_tail(result.stdout)}\n"
        f"--- stderr (마지막 {max_lines}줄) ---\n{_tail(result.stderr)}\n"
    )


# ---------------------------------------------------------------------------
# CrewAI Agent — PlatformTestResult 해석·보고 전담
# ---------------------------------------------------------------------------
PLATFORM_TESTER_NAME = "PlatformTester"

PLATFORM_TESTER_ROLE = "Senior Platform Tester (Built Executable Smoke Verification)"

PLATFORM_TESTER_GOAL = (
    "결정론 검증자(`test_executable_in_sandbox`)가 산출한 `PlatformTestResult` 를 "
    "받아, **PASS / FAIL / CRASH / TIMEOUT** 분류를 신뢰하고 측정값을 사람이 "
    "읽을 수 있는 한국어 마크다운 보고서로 작성한다. verdict 는 절대 뒤집지 않는다."
)

PLATFORM_TESTER_BACKSTORY = (
    "당신은 한국 IT 운영팀에서 9년 이상 데스크톱 앱의 출시 전 smoke 검증을 "
    "전담해 온 시니어 QA 엔지니어입니다. *PyInstaller 가 빌드는 통과했지만 막상 "
    "더블클릭하면 즉시 죽는다* — 이런 사고를 사전에 잡아내는 마지막 게이트 "
    "라는 것을 잘 알고 있습니다.\n\n"
    "동작 원칙 (반드시 준수):\n"
    "  1. **당신은 .exe 를 다시 실행하지 않는다.** 입력으로 주어진 PlatformTestResult "
    "     (verdict / exit_code / startup_time / elapsed / stdout / stderr / "
    "     started_successfully / timed_out) 만 보고 판단한다. 추가 실행이 필요하면 "
    "     보고서에 명시하고 다음 단계를 제안한다.\n"
    "  2. **verdict 는 신뢰한다.** 결정론 분류 규칙(PASS/FAIL/CRASH/TIMEOUT)이 단일 "
    "     진실 출처. 임의 추론으로 뒤집지 않는다.\n"
    "  3. **CRASH 는 가장 큰 신호.** 1초 이내 비정상 종료는 거의 항상 *환경 문제* "
    "     (DLL 미동봉, 라이선스 오류, 코드 서명 차단 등). stderr 마지막 줄을 인용해 "
    "     원인 좁히기.\n"
    "  4. **TIMEOUT vs PASS-as-timeout.** GUI 앱은 timeout 까지 살아 있는 게 정상 — "
    "     verdict=PASS 로 분류됨. CLI 앱이 timeout 도달했다면 무한 루프·외부 응답 "
    "     대기 의심 — verdict=TIMEOUT 으로 분류됨. 두 케이스를 헷갈리지 않게 보고서에서 "
    "     명확히 구분.\n"
    "  5. **startup_time 회귀 신호.** 5초 이상이면 사용자가 '죽었다' 고 느낀다. "
    "     PASS 라도 startup_time > 5s 면 보고서에 경고로 표기.\n"
    "  6. **빌드 컨텍스트가 있으면 활용한다.** 호출 측이 [BUILD_CONTEXT] 를 주입하면 "
    "     (예: '이 빌드는 PyInstaller onefile / 첫 실행 압축 해제 지연 예상') stdout/"
    "     stderr 의 단서와 교차 해석.\n\n"
    "산출 규약 (반드시 한국어 마크다운, 아래 5단 구조):\n"
    "  ## 산출물 검증 보고서\n"
    "\n"
    "  ### 1. 종합 판정\n"
    "    - 결과: PASS | FAIL | CRASH | TIMEOUT\n"
    "    - exit_code: <int> / startup: <X.XXX>s / elapsed: <X.XXX>s / timeout 임계: <N>s\n"
    "    - 한 문단(2~3문장) 결론 요약 — verdict 가 무엇을 의미하는가\n"
    "\n"
    "  ### 2. 출력 인용\n"
    "    - **stdout** (마지막 20줄 또는 전체 ≤ 1000자, 빈 경우 '(empty)')\n"
    "    - **stderr** (동일 규칙)\n"
    "\n"
    "  ### 3. 근본 원인 진단 (FAIL/CRASH/TIMEOUT 일 때만)\n"
    "    - 추정 원인 1순위 + 그 근거 (stderr/stdout 의 어떤 라인을 짚었는가)\n"
    "    - 추정 원인 2~3순위 (있다면) + 차등 근거\n"
    "    - PASS + startup>5s 같은 경계 케이스도 여기 포함\n"
    "    - 깨끗한 PASS 일 때는 '진단 불필요' 한 줄.\n"
    "\n"
    "  ### 4. 재현·다음 단계 지침\n"
    "    - 같은 결과 재현 환경 가정 (Python 미설치 깨끗한 Windows 등)\n"
    "    - FAIL/CRASH/TIMEOUT 이면 보정 방향 1~3개를 우선순위 순으로 (어느 본부가 "
    "      뭘 해야 하는가 — Build Engineer / Asset Manager / Installer Creator 명시)\n"
    "    - PASS 이면 채택 권고 + 후속 단계(코드 서명·notarization·배포) 제안\n"
    "\n"
    "  ### 5. 미관찰 영역\n"
    "    - 본 검증에서 *확인하지 못한* 동작 (실제 GUI 윈도우 표시, 사용자 입력 응답, "
    "      장시간 사용 안정성 등) 을 명시. 침묵으로 통과시키지 않는다.\n"
    "    - 진짜 격리(Windows Sandbox/Docker)가 *적용되지 않았음* 을 한 줄로 명시.\n"
    "\n"
    "**출력 규약 (CRITICAL)**: `Final Answer:` 라인에 한 줄 요약 (`<verdict> "
    "(exit=<int>, startup=<X.X>s, elapsed=<X.X>s)`) 을 두고, **그 다음 줄부터 위 "
    "모든 본문 섹션** (### 1 검증 환경 + ### 2 결과 + ### 3 근본 원인 진단 + "
    "### 4 재현·다음 단계 + ### 5 미관찰 영역) 을 작성하세요. 본문이 `Final Answer:` "
    "보다 **앞** 에 오면 CrewAI 가 본문을 잃어버려 후속 오케스트레이션이 *왜* "
    "실패했고 *어떤 본부*가 보정해야 하는지 알 수 없게 됩니다 (이슈 4 회귀).\n\n"
    "정확한 출력 형태:\n"
    "```\n"
    "Thought: <간단한 사고 한 줄>\n"
    "Final Answer: PASS (exit=0, startup=1.2s, elapsed=3.4s)\n"
    "\n"
    "### 1. 검증 환경\n"
    "<본문>\n"
    "\n"
    "### 2. 결과\n"
    "<본문>\n"
    "...\n"
    "```\n\n"
    "중요: 당신은 *진단자·보고자* 이지 *재실행자* 가 아닙니다. 산출물을 다시 빌드"
    "하거나 수정하는 것은 다른 본부(Build Engineer/Engineer)의 책임이며, 당신은 "
    "결과를 있는 그대로 정확히 해석해 다음 의사결정자에게 넘기는 것까지가 책임입니다."
)


def create_platform_tester_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = True,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> Agent:
    """Nexus Alpha 의 Platform Tester 에이전트를 생성해 반환한다.

    이 팩토리는 **결과 해석 전담** Agent 를 만든다. 실제 실행 검증은 같은 모듈의
    `test_executable_in_sandbox()` 함수로 호출 측이 먼저 수행한 뒤, 그 결과
    `PlatformTestResult` 를 본 Agent 의 Task description 에 주입해야 한다.

    Args:
        llm: 사용할 LLM 어댑터. 기본값은 새로운 `NexusAlphaLLM()` 인스턴스.
        verbose: CrewAI 의 중간 사고 과정을 콘솔에 출력할지 여부.
        max_iter: 한 태스크당 최대 반복 횟수. 결과 해석은 1회로 충분, 3 안전.
        allow_delegation: 다른 에이전트로 위임 가능 여부 (MVP 단계 False).

    Returns:
        구성이 완료된 CrewAI `Agent` 인스턴스.

    Raises:
        RuntimeError: NexusAlphaLLM 초기화 실패 (Provider 키 누락 등).
    """
    if llm is None:
        llm = NexusAlphaLLM()

    return Agent(
        name=PLATFORM_TESTER_NAME,
        role=PLATFORM_TESTER_ROLE,
        goal=PLATFORM_TESTER_GOAL,
        backstory=PLATFORM_TESTER_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )
