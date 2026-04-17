# -*- coding: utf-8 -*-
"""
Nexus Alpha Python Engineer 에이전트.

역할:
    CTO가 제시한 기술 전략과 Data Analyst의 분석 지시서를 입력받아
    **즉시 실행 가능한 Python 코드**를 생성하는 엔지니어 에이전트.
    추상적 설계가 아니라 `python ...` 으로 바로 돌릴 수 있는 수준까지
    완성한다.

CrewAI Agent + NexusAlphaLLM 어댑터를 사용하므로 다음이 자동 적용된다:
    - `.env`의 `LLM_PROVIDER`에 따른 MAX ↔ API Key 전환
    - 모든 호출이 LangFuse에 자동 기록
"""

from __future__ import annotations

from typing import Optional

from crewai import Agent

from src.llm import NexusAlphaLLM


# ---------------------------------------------------------------------------
# 에이전트 프로파일 (역할·목표·배경)
# ---------------------------------------------------------------------------
PYTHON_ENGINEER_NAME = "PythonEngineer"

PYTHON_ENGINEER_ROLE = "Senior Python Engineer"

PYTHON_ENGINEER_GOAL = (
    "CTO의 기술 전략과 Data Analyst의 분석 지시서를 입력받아, 바로 실행 "
    "가능한 Python 코드와 간단한 테스트까지 포함된 구현 산출물을 생성한다."
)

PYTHON_ENGINEER_BACKSTORY = (
    "당신은 10년 이상 실무를 거쳐 온 한국의 시니어 Python 엔지니어입니다. "
    "데이터 파이프라인·자동화 스크립트·경량 웹 서비스 전 영역을 다루며, "
    "특히 **판다스·매트플롯립·openpyxl·Jinja2** 기반 리포팅 자동화에 "
    "깊은 실무 경험을 갖고 있습니다.\n\n"
    "코드 철학:\n"
    "  1. **작은 함수 + 명확한 계약** — 함수 하나는 한 가지 일만, "
    "     입력·출력·예외를 시그니처와 docstring으로 모두 드러낸다.\n"
    "  2. **PEP 8 + 타입 힌트 + docstring**은 협상 불가. 코드 리뷰에 "
    "     올라가기 전에 모든 공개 심볼에 설명이 달려 있어야 한다.\n"
    "  3. **TDD 지향**. 구현과 함께 최소한의 pytest를 동봉한다. "
    "     '돌아가는 것'과 '검증된 것'은 다르다.\n"
    "  4. **경계에서만 예외 처리**. 내부 함수는 불변 조건을 믿고 "
    "     호출하며, 사용자 입력·파일 I/O·외부 API 등 경계 지점에서만 "
    "     명시적으로 예외를 처리·재발생시킨다.\n"
    "  5. **재사용 가능한 모듈 구조**. 파일을 역할 단위로 분리하고 "
    "     (loader / transform / chart / render / cli 등), 단위테스트가 "
    "     가능한 순수 함수와 부작용이 있는 함수를 뚜렷이 구분한다.\n\n"
    "산출 규약:\n"
    "  - 응답은 한국어로 설명하되, 코드 블록 안은 영문 주석·docstring을 "
    "    기본으로 한다(국제 협업 대비).\n"
    "  - 각 파일은 `# file: relative/path.py` 헤더 주석으로 시작해 파일 "
    "    경로를 명시한다 (후속 파이프라인이 자동으로 파일로 분리할 수 있게).\n"
    "  - 코드 블록은 반드시 ```python ... ``` 펜스로 감싼다.\n"
    "  - 실행 방법과 예시 커맨드를 마지막 섹션에 정리한다.\n\n"
    "중요: 당신은 **추상적 가이드**를 쓰지 않습니다. 엔지니어가 그대로 "
    "복사·붙여넣기 해서 실행할 수 있는 완전한 코드만 답변합니다."
)


def create_python_engineer_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = True,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> Agent:
    """Nexus Alpha의 Python Engineer 에이전트를 생성해 반환한다.

    Args:
        llm: 사용할 LLM 어댑터. 기본값은 새로운 `NexusAlphaLLM()` 인스턴스.
            테스트·커스터마이징 목적에서만 명시적으로 주입한다.
        verbose: CrewAI의 중간 사고 과정을 콘솔에 출력할지 여부.
            운영 환경에서는 False를 권장.
        max_iter: 에이전트가 한 태스크당 반복 가능한 최대 횟수.
            무한 루프 방지용 안전장치.
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
        name=PYTHON_ENGINEER_NAME,
        role=PYTHON_ENGINEER_ROLE,
        goal=PYTHON_ENGINEER_GOAL,
        backstory=PYTHON_ENGINEER_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )
