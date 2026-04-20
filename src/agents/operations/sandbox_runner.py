# -*- coding: utf-8 -*-
"""
Nexus Alpha Sandbox Runner (운영 지원 본부, Phase 2-P4).

본 모듈은 두 가지를 함께 제공한다.

1. **`run_python_in_sandbox(code, timeout_sec=30)` 함수**
       LLM과 무관한 결정론적 실행자. 주어진 Python 코드 문자열을 임시
       작업 디렉터리에서 별도 프로세스로 실행하고, stdout/stderr/exit code/
       경과 시간/타임아웃 여부를 `SandboxResult` 데이터클래스로 반환한다.
       향후 워크플로우가 직접 호출해 결과를 다음 단계로 전달한다.

2. **`create_sandbox_runner_agent()` 팩토리**
       위 함수가 산출한 `SandboxResult`를 *해석·보고* 하는 CrewAI Agent.
       PASS / FAIL / TIMEOUT 으로 분류하고 근본 원인 진단·재현 지침을
       한국어 마크다운 리포트로 작성한다. Agent 자체는 코드를 실행하지
       않으며, 호출 측 워크플로우가 함수 결과를 Task description에 주입한다.

⚠️  보안 한계 — 절대 진짜 샌드박스가 아니다:
    `subprocess` + `timeout`만으로는 OS 레벨 격리가 없다. 실행되는 코드는
    호스트의 파일 시스템·네트워크·환경변수에 모두 접근 가능하다. 신뢰할 수
    없는 코드를 실행하면 안 된다. 진짜 격리(컨테이너/VM/seccomp/firejail
    등)는 Phase 3 이후 또는 별도 작업으로 분리한다.

Code Reviewer(QA, Phase 2-P2)와의 관계:
    Code Reviewer는 *코드를 읽고* 정적 점검만 수행한다. Sandbox Runner는
    *코드를 실행하고* 동적으로 검증한다. 두 에이전트는 보완 관계이며,
    워크플로우에서 QA 다음 단계로 들어가는 것이 자연스럽다.
"""

from __future__ import annotations

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
class SandboxResult:
    """`run_python_in_sandbox` 의 구조화 산출물.

    Attributes:
        exit_code: 자식 프로세스 종료 코드. 정상 종료 시 0. 타임아웃 시 -1.
        stdout: 자식 프로세스의 표준 출력 (UTF-8 디코딩, 끝의 개행은 보존).
        stderr: 자식 프로세스의 표준 오류 (UTF-8 디코딩).
        elapsed_sec: 실행 시작부터 종료까지 경과 시간(초). 타임아웃이면 timeout_sec.
        timed_out: 타임아웃으로 강제 종료됐는지 여부.
        timeout_sec: 호출 시 사용된 타임아웃 임계값(초).
        verdict: PASS / FAIL / TIMEOUT 셋 중 하나로 분류된 결과.
            - PASS: exit_code == 0
            - TIMEOUT: timed_out == True
            - FAIL: exit_code != 0 and not timed_out
        workdir: 실제 사용된 임시 작업 디렉터리 경로(이미 정리된 상태일 수 있음).
    """

    exit_code: int
    stdout: str
    stderr: str
    elapsed_sec: float
    timed_out: bool
    timeout_sec: int
    verdict: str = field(init=False)
    workdir: Optional[Path] = None

    def __post_init__(self) -> None:
        if self.timed_out:
            self.verdict = "TIMEOUT"
        elif self.exit_code == 0:
            self.verdict = "PASS"
        else:
            self.verdict = "FAIL"


# ---------------------------------------------------------------------------
# 결정론적 실행자 (LLM 무관)
# ---------------------------------------------------------------------------
def run_python_in_sandbox(
    code: str,
    timeout_sec: int = 30,
    extra_env: Optional[dict[str, str]] = None,
) -> SandboxResult:
    """주어진 Python 코드를 별도 프로세스에서 실행하고 결과를 반환한다.

    실행 절차:
        1. 임시 디렉터리(`tempfile.TemporaryDirectory`) 생성
        2. 디렉터리에 `_sandbox_main.py` 파일로 코드 기록
        3. `sys.executable` 로 해당 파일을 실행 (cwd=임시 디렉터리)
        4. stdout/stderr 캡처 + 타임아웃 적용
        5. 임시 디렉터리는 with 블록 종료 시 자동 삭제

    Args:
        code: 실행할 Python 소스 문자열. shebang은 무시된다.
        timeout_sec: 자식 프로세스가 강제 종료되기 전까지 허용 시간(초).
            기본 30초. 음수 또는 0은 ValueError.
        extra_env: 자식 프로세스에 주입할 추가 환경변수. 부모 환경에 덮어쓴다.

    Returns:
        실행 결과를 담은 `SandboxResult`. 타임아웃 시 verdict="TIMEOUT".

    Raises:
        ValueError: timeout_sec ≤ 0
        TypeError: code가 문자열이 아닌 경우

    보안 경고:
        본 함수는 진짜 샌드박스가 아니다. 자식 프로세스는 호스트의 파일/네트워크/
        환경변수에 모두 접근 가능하다. 신뢰할 수 없는 코드는 실행하지 말 것.
    """
    if not isinstance(code, str):
        raise TypeError(f"code must be str, got {type(code).__name__}")
    if timeout_sec <= 0:
        raise ValueError(f"timeout_sec must be positive, got {timeout_sec}")

    with tempfile.TemporaryDirectory(prefix="nexus_sandbox_") as tmpdir:
        workdir = Path(tmpdir)
        script_path = workdir / "_sandbox_main.py"
        script_path.write_text(code, encoding="utf-8")

        env = None
        if extra_env:
            import os

            env = {**os.environ, **extra_env}

        start = time.monotonic()
        timed_out = False
        stdout_text = ""
        stderr_text = ""
        exit_code = -1

        try:
            completed = subprocess.run(  # noqa: S603 (의도적 subprocess 호출)
                [sys.executable, str(script_path)],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                env=env,
            )
            exit_code = completed.returncode
            stdout_text = completed.stdout or ""
            stderr_text = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout_text = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
            stderr_text = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        finally:
            elapsed = time.monotonic() - start

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            elapsed_sec=round(elapsed, 3),
            timed_out=timed_out,
            timeout_sec=timeout_sec,
            workdir=workdir,
        )


# ---------------------------------------------------------------------------
# CrewAI Agent — SandboxResult 해석·보고 전담
# ---------------------------------------------------------------------------
SANDBOX_RUNNER_NAME = "SandboxRunner"

SANDBOX_RUNNER_ROLE = "Senior Sandbox Runner (Dynamic Verification & Diagnosis)"

SANDBOX_RUNNER_GOAL = (
    "결정론적 실행자(`run_python_in_sandbox`)가 산출한 `SandboxResult`를 입력받아, "
    "**PASS / FAIL / TIMEOUT** 으로 분류하고 실패·타임아웃의 근본 원인 진단과 "
    "재현·다음 단계 지침을 한국어 마크다운 보고서로 작성한다."
)

SANDBOX_RUNNER_BACKSTORY = (
    "당신은 한국 IT 운영팀에서 8년 이상 자동화 스크립트의 실행·장애 대응을 "
    "전담해 온 시니어 엔지니어입니다. '실행해 보지 않은 코드는 코드가 아니라 "
    "가설이다'는 원칙을 일관되게 지켜 왔고, 실패 로그를 빠르게 분류·진단하는 "
    "데 강점이 있습니다.\n\n"
    "동작 원칙 (반드시 준수):\n"
    "  1. **당신은 코드를 다시 실행하지 않는다.** 입력으로 주어진 SandboxResult "
    "     (exit_code / stdout / stderr / elapsed_sec / timed_out / verdict) "
    "     만 보고 판단한다. 추가 실행이 필요하다고 느끼면 그 사실을 보고서에 "
    "     명시하고 다음 단계를 제안한다.\n"
    "  2. **분류는 SandboxResult.verdict 를 신뢰한다.** PASS / FAIL / TIMEOUT은 "
    "     이미 결정론적으로 판정된 값이다. 임의로 뒤집지 않는다.\n"
    "  3. **stderr에서 신호를 찾는다.** 실패의 근본 원인은 거의 항상 stderr의 "
    "     마지막 traceback에 있다. 라인을 인용하고 어떤 예외인지 명시한다.\n"
    "  4. **재현 지침은 환경 가정과 함께.** 'Python 3.13 / 표준 라이브러리만' "
    "     같은 가정을 명시해야 다른 사람이 같은 결과를 본다.\n"
    "  5. **TIMEOUT은 별도 카테고리로 다룬다.** 무한 루프 / 입력 대기 / 외부 "
    "     API 응답 지연 등 후보를 나열하고, 어느 것이 가장 가능성 높은지 "
    "     stderr·stdout의 단서로 좁힌다.\n"
    "  6. **PASS도 코멘트한다.** stdout이 기대 형식인지, 부수효과(파일 생성·"
    "     네트워크 호출 흔적)는 없는지 한 줄로 짚는다. 단순 통과 도장이 아니다.\n\n"
    "산출 규약 (반드시 한국어 마크다운, 아래 5단 구조 그대로):\n"
    "  ## 실행 보고서\n"
    "\n"
    "  ### 1. 종합 판정\n"
    "    - 결과: `PASS` / `FAIL` / `TIMEOUT` (입력 verdict 그대로)\n"
    "    - exit_code: <int> / elapsed: <X.XXX>s / timeout 임계: <N>s\n"
    "    - 한 문단(2~3문장) 결론 요약\n"
    "\n"
    "  ### 2. 출력 인용\n"
    "    - **stdout** (마지막 20줄 또는 전체 ≤ 1000자, 빈 경우 '(empty)')\n"
    "    - **stderr** (동일 규칙)\n"
    "\n"
    "  ### 3. 근본 원인 진단 (FAIL/TIMEOUT 일 때만)\n"
    "    - 추정 원인 1순위 + 그 근거 (stderr의 어떤 라인을 짚었는가)\n"
    "    - 추정 원인 2~3순위 (있다면) + 차등 근거\n"
    "    - PASS 일 때는 '진단 불필요' 한 줄.\n"
    "\n"
    "  ### 4. 재현·다음 단계 지침\n"
    "    - 같은 결과를 재현하기 위한 환경 가정 (Python 버전, 의존성 등)\n"
    "    - FAIL/TIMEOUT 이면 보정 방향 1~3개를 우선순위 순으로\n"
    "    - PASS 이면 채택 권고 + 후속 검증(예: 통합 테스트) 제안\n"
    "\n"
    "  ### 5. 미관찰 영역\n"
    "    - 이번 실행에서 *확인하지 못한* 동작(예: 별도 입력으로의 분기, 외부 "
    "      파일 의존)을 명시. 침묵으로 통과시키지 않는다.\n"
    "\n"
    "마지막 줄은 반드시 `Final Answer:` 로 시작하는 한 줄 — `Final Answer: "
    "PASS|FAIL|TIMEOUT (exit=<int>, elapsed=<X.XXX>s)` 형태로 후속 오케스트레이션이 "
    "명확히 분기할 수 있게 합니다.\n\n"
    "중요: 당신은 *진단자·보고자*이지 *실행자*가 아닙니다. 코드의 재실행, 수정, "
    "재구현은 다른 에이전트(Engineer / Code Reviewer)의 책임이며, 당신은 결과를 "
    "있는 그대로 정확히 해석해 다음 의사결정자에게 넘기는 것까지가 책임입니다."
)


def create_sandbox_runner_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = True,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> Agent:
    """Nexus Alpha의 Sandbox Runner 에이전트를 생성해 반환한다.

    이 팩토리는 **결과 해석 전담** Agent를 만든다. 실제 코드 실행은 같은
    모듈의 `run_python_in_sandbox()` 함수로 호출 측이 먼저 수행한 뒤, 그
    결과(`SandboxResult`)를 본 Agent의 Task description에 주입해야 한다.

    Args:
        llm: 사용할 LLM 어댑터. 기본값은 새로운 `NexusAlphaLLM()` 인스턴스.
            테스트·커스터마이징 목적에서만 명시적으로 주입한다.
        verbose: CrewAI의 중간 사고 과정을 콘솔에 출력할지 여부.
            운영 환경에서는 False를 권장.
        max_iter: 에이전트가 한 태스크당 반복 가능한 최대 횟수.
            결과 해석은 한 번에 끝나야 하므로 기본 3회로 충분.
        allow_delegation: 다른 에이전트로 작업을 위임할 수 있는지 여부.
            MVP 단계에서는 단독 작업 원칙으로 False.

    Returns:
        구성이 완료된 CrewAI `Agent` 인스턴스.

    Raises:
        RuntimeError: `NexusAlphaLLM` 초기화 단계에서 Provider 생성에
            실패한 경우 (예: API Key 모드인데 키 누락).
    """
    if llm is None:
        llm = NexusAlphaLLM()

    return Agent(
        name=SANDBOX_RUNNER_NAME,
        role=SANDBOX_RUNNER_ROLE,
        goal=SANDBOX_RUNNER_GOAL,
        backstory=SANDBOX_RUNNER_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )


# ---------------------------------------------------------------------------
# 헬퍼: SandboxResult를 Agent Task description으로 직렬화
# ---------------------------------------------------------------------------
def format_sandbox_result_for_task(result: SandboxResult, *, max_lines: int = 20) -> str:
    """`SandboxResult` 를 Agent Task description에 끼워 넣기 좋은 텍스트로 변환.

    너무 긴 stdout/stderr는 마지막 `max_lines` 줄로 잘라낸다. Agent의 토큰
    예산을 보호하기 위함. 호출 측에서 이 결과를 Task description 본문에 그대로
    붙이면 된다.
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
        f"elapsed_sec: {result.elapsed_sec}\n"
        f"timeout_sec: {result.timeout_sec}\n"
        f"timed_out: {result.timed_out}\n"
        f"--- stdout (마지막 {max_lines}줄) ---\n{_tail(result.stdout)}\n"
        f"--- stderr (마지막 {max_lines}줄) ---\n{_tail(result.stderr)}\n"
    )
