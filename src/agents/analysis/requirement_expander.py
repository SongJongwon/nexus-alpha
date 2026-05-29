# -*- coding: utf-8 -*-
"""
Nexus Alpha Requirement Expander 에이전트 (업무 분석 본부, Phase 2.5 / v3).

역할:
    사용자의 자연어 요청 1줄을 받아 **구조화된 요구 스펙(YAML)** 으로 확장하는
    분석 에이전트. v3 자율 반복 루프(`Iteration Controller`)의 첫 단계로,
    이후 Gap Analyst 가 산출물 충족도를 검증할 때 비교 기준이 되는 *원본 사양*
    역할을 한다.

핵심 설계 결정 (`docs/architecture/nexus_alpha_v3.md` §4-1):
    - **가정과 미해결 질문은 절대 숨기지 않는다.** 모호한 요구를 임의로
      해석한 경우, 그 해석을 반드시 `assumptions:` 또는 `open_questions:` 에
      명시한다. 침묵으로 통과시키지 않는 것이 자율 반복 루프의 안정성 핵심.
    - 출력은 후속 Gap Analyst 가 **자동 파싱 가능한** YAML — 평탄 구조 우선.

조직도 정합:
    - 본 에이전트는 `nexus_alpha_org_v4.md` §3-1 (업무 분석 본부) 소속.
    - `nexus_alpha_v3.md` §4-1 본문에 `src/agents/planning/` 로 적힌 위치는
      확정 조직도와 어긋나므로, 확정 조직도를 따라 `src/agents/analysis/` 에 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from crewai import Agent

from src.llm import NexusAlphaLLM


# ---------------------------------------------------------------------------
# v13 Phase 6.2 (PR #226) — 도메인 결정론 매처 + 체크리스트 템플릿
#
# 배경: BIM 빌드 사례 분석 — "진짜 3D vs 가짜 2D" 미구분 결함 + Convergence
# Judge 의 성급한 종료 결함. 본 모듈에 *도메인 detect + 템플릿 체크리스트*
# 결정론 인프라 추가. PM 확정 사양 (docs/architecture/phase6_proposal.md):
#   - 옵션 B 만 (PyPI JSON, 비용 0원)
#   - 3D 도메인 우선 (BIM 검증 후 확장)
#   - 회귀 0 절대 준수 (domain_checklist 사용 안 하면 기존 동작)
# ---------------------------------------------------------------------------


@dataclass
class ChecklistItem:
    """도메인 체크리스트 1 항목 — Convergence Judge Rule 0 입력 (v13 Phase 6.2).

    Attributes:
        id: kebab-case 도메인 ID (예: ``"3d-camera-orbit"``).
            안정 식별자 — 미충족 항목 ID 가 다음 iter Engineer prompt 에 주입됨.
        domain: 도메인 카테고리 (예: ``"3d_visualization"``).
        description: 한국어 1 문장 요구사항 설명.
        must_satisfy: True 면 Rule 0 강제 검증 대상.
            False 면 caveat 안내만 (현재 미사용 — 향후 minor 등급 도입 시).
        detect_keywords: ``engineer_output`` + ``qa_result`` 에 등장하면
            *충족된 것* 으로 간주하는 키워드 list. 대소문자 무시 부분 매칭.
    """

    id: str
    domain: str
    description: str
    must_satisfy: bool = True
    detect_keywords: list[str] = field(default_factory=list)


# 도메인별 사용자 요청 키워드 패턴 (대소문자 무시 부분 매칭)
# 3D 우선 — PM 의사결정 #4. BIM 검증 후 data_viz / ml / distributed 확장.
_DOMAIN_PATTERNS: dict[str, list[str]] = {
    "3d_visualization": [
        # 영문
        "3d", "WebGL", "Three.js", "BIM", "CAD",
        "Bloch sphere", "Mesh", "Camera", "Orbit", "renderer",
        # 한국어
        "3차원", "삼차원", "공간 시각화", "건축 모델",
    ],
}


# 3D 도메인 템플릿 체크리스트 (4 항목) — BIM 본질 검증 핵심.
_TEMPLATE_3D_CHECKLIST: list[ChecklistItem] = [
    ChecklistItem(
        id="3d-camera-orbit",
        domain="3d_visualization",
        description="카메라 Orbit 회전 (마우스 드래그로 카메라 위치 조정)",
        must_satisfy=True,
        detect_keywords=[
            "OrbitControls", "mouseDown", "rotate", "camera.position",
            "orbit", "azimuth", "elevation",
        ],
    ),
    ChecklistItem(
        id="3d-webgl-vs-canvas",
        domain="3d_visualization",
        description="WebGL (Three.js) vs Canvas 2D 아키텍처 선택 명시",
        must_satisfy=True,
        detect_keywords=[
            "WebGLRenderer", "three.js", "THREE.",
            "Canvas2DContext", 'getContext("2d")', "getContext('2d')",
        ],
    ),
    ChecklistItem(
        id="3d-interactive-controls",
        domain="3d_visualization",
        description="줌/팬/리셋 인터랙티브 컨트롤 (사용자 입력 응답)",
        must_satisfy=True,
        detect_keywords=[
            "zoom", "pan", "reset", "wheel", "controls.update",
            "addEventListener", "mousewheel",
        ],
    ),
    ChecklistItem(
        id="3d-real-3d-not-isometric",
        domain="3d_visualization",
        description="진짜 3D (Z-축 회전) vs 가짜 2D isometric 구분 — BIM 본질",
        must_satisfy=True,
        detect_keywords=[
            "rotateY", "rotation.z", "Vector3", "depthBuffer", "depth_buffer",
            "PerspectiveCamera", "PointLight", "DirectionalLight",
        ],
    ),
]


# 도메인 → 템플릿 체크리스트 매핑.
# 새 도메인 추가 시 본 dict 와 _DOMAIN_PATTERNS 양쪽 갱신.
_DOMAIN_TEMPLATES: dict[str, list[ChecklistItem]] = {
    "3d_visualization": _TEMPLATE_3D_CHECKLIST,
}


def _detect_domain(user_request: str) -> list[str]:
    """사용자 자연어 요청 → 도메인 ID list (결정론 키워드 매칭).

    여러 도메인 동시 매칭 가능 (예: "3D 데이터 시각화 대시보드" → 3d + data_viz).
    매칭 0건 시 빈 list 반환 — 호출자는 도메인 체크리스트 사용 안 함.

    Args:
        user_request: 사용자 요청 원문.

    Returns:
        매칭된 도메인 ID list (e.g. ``["3d_visualization"]``).
    """
    if not user_request:
        return []
    lower = user_request.lower()
    matches: list[str] = []
    for domain, keywords in _DOMAIN_PATTERNS.items():
        if any(kw.lower() in lower for kw in keywords):
            matches.append(domain)
    return matches


# ---------------------------------------------------------------------------
# v13 Phase 6.E P1 (PR #235) — 플랫폼 의도 결정론 매처
#
# 배경 (crash analysis 2026-05-29): "Three.js BIM 뷰어"(web) 요청인데 엔지니어가
# 7/7 PyQt 데스크탑으로 드리프트 → Three.js/WebGL 0매칭 → Rule 0 영구 IMPROVE →
# (P0 가드로) BLOCKED. P1 은 *실제로 web/Three.js 로 수렴* 하게 만든다.
#   - 예방: target=web 이면 엔지니어 프롬프트에 데스크탑 GUI 금지 제약 주입
#   - 탐지: web 의도인데 데스크탑 마커 산출 → Convergence Judge PLATFORM_DRIFT
# 회귀 0: unspecified 면 제약 미주입 + 드리프트 검사 skip (기존 동작 보존).
# ---------------------------------------------------------------------------
_WEB_PLATFORM_KEYWORDS: list[str] = [
    "three.js", "threejs", "webgl", "web", "브라우저", "browser", "html", "canvas",
]
_DESKTOP_PLATFORM_KEYWORDS: list[str] = [
    "pyqt", "pyside", "tkinter", "데스크탑", "데스크톱",
]


def _detect_platform(user_request: str) -> str:
    """사용자 요청 → 플랫폼 의도 ("web" | "desktop" | "unspecified") 결정론 매칭.

    동작:
        - web 시그널만 → "web"
        - 데스크탑 시그널만 → "desktop"
        - 둘 다 또는 둘 다 없음 → "unspecified" (모호 — 제약 미주입, 회귀 0)

    Args:
        user_request: 사용자 요청 원문.

    Returns:
        "web" | "desktop" | "unspecified".

    Note:
        LLM 무관 결정론. 명시 플랫폼이 Track 기본값(Track A 데스크탑 편향)을 이긴다.
    """
    if not user_request:
        return "unspecified"
    lower = user_request.lower()
    has_web = any(kw in lower for kw in _WEB_PLATFORM_KEYWORDS)
    has_desktop = any(kw in lower for kw in _DESKTOP_PLATFORM_KEYWORDS)
    if has_web and not has_desktop:
        return "web"
    if has_desktop and not has_web:
        return "desktop"
    return "unspecified"


def build_domain_checklist(user_request: str) -> list[ChecklistItem]:
    """사용자 요청 → 도메인별 템플릿 체크리스트 합성.

    동작:
        1. ``_detect_domain(user_request)`` 으로 매칭 도메인 식별
        2. 매칭된 각 도메인의 템플릿 체크리스트를 *합집합* 반환
        3. 매칭 0 → 빈 list (Rule 0 자동 skip, 기존 동작 보존)

    Args:
        user_request: 사용자 요청 원문.

    Returns:
        ChecklistItem list — Convergence Judge ``judge_convergence(
        domain_checklist=...)`` 에 그대로 전달 가능.

    Note:
        본 함수는 LLM 무관 — 결정론적. 동일 입력 → 동일 출력.
    """
    domains = _detect_domain(user_request)
    if not domains:
        return []
    checklist: list[ChecklistItem] = []
    for domain in domains:
        template = _DOMAIN_TEMPLATES.get(domain, [])
        checklist.extend(template)
    return checklist


# ---------------------------------------------------------------------------
# 에이전트 프로파일 (역할·목표·배경)
# ---------------------------------------------------------------------------
REQUIREMENT_EXPANDER_NAME = "RequirementExpander"

REQUIREMENT_EXPANDER_ROLE = "Senior Requirements Analyst (Spec Expansion)"

REQUIREMENT_EXPANDER_GOAL = (
    "사용자의 1~수문장짜리 자연어 요청을 받아, 후속 에이전트가 *바로 작업할 수 "
    "있는 수준* 의 구조화 요구 스펙을 YAML 형식으로 산출한다. 모호한 부분은 "
    "임의 해석하지 말고 `assumptions` 또는 `open_questions` 로 분리해 명시한다."
)

REQUIREMENT_EXPANDER_BACKSTORY = (
    "당신은 한국 IT 조직에서 7년 이상 요구 분석을 전담해 온 시니어 분석가입니다. "
    "수많은 PRD·BRD·유저스토리 작성을 거치며, '추측을 명시적 가정으로 적는 것'이 "
    "프로젝트 후반 재작업을 가장 크게 줄인다는 것을 학습했습니다.\n\n"
    "확장 철학:\n"
    "  1. **가정은 숨기지 않는다.** 사용자 요청에 빠진 정보를 *어쩔 수 없이* 메워 "
    "     넣을 때는 반드시 `assumptions:` 항목에 한 줄로 적는다. 후속 단계가 그 "
    "     가정을 검토·반박할 수 있어야 한다.\n"
    "  2. **답이 없는 질문도 적는다.** 핵심 결정이지만 사용자가 답하지 않은 항목은 "
    "     `open_questions:` 에 적는다. 이 질문이 비어 있지 않으면 Iteration "
    "     Controller 가 BLOCKED 판정의 근거로 활용한다.\n"
    "  3. **요구는 ID로 추적 가능하게.** `F-001`(functional), `N-001`(nonfunctional) "
    "     형식의 안정 식별자를 부여한다. 이후 Gap Analyst 가 이 ID로 충족 여부를 "
    "     보고한다.\n"
    "  4. **우선순위는 must / should / could 셋만.** Won't 는 명시적 제외이므로 "
    "     본 단계에서 다루지 않는다(사용자가 직접 빼야 할 일).\n"
    "  5. **deliverables 는 산출 *형태* 에 집중.** 어떤 언어로, 어떤 실행 단위 "
    "     (CLI/스크립트/.exe/웹앱)로 만들지를 명시한다. 추론 결과면 가정으로 표시.\n\n"
    "산출 규약 (반드시 한국어 마크다운 + ```yaml 블록 1개, 아래 2단 구조):\n"
    "  ## 요구 스펙\n"
    "\n"
    "  ```yaml\n"
    "  goal: |\n"
    "    사용자가 적은 원 요청을 그대로 옮겨 적기 (수정·요약 금지)\n"
    "  deliverables:\n"
    "    - type: <executable | library | script | analysis-report | dashboard | other>\n"
    "      platform: <Windows desktop | Web | macOS | Linux | cross-platform | unknown>\n"
    "      form_factor: <GUI | CLI | API | notebook | ...>\n"
    "      language: <Python | TypeScript | ...>\n"
    "  functional:\n"
    "    - id: F-001\n"
    "      desc: <한 줄 기능 요구>\n"
    "      priority: <must | should | could>\n"
    "  nonfunctional:\n"
    "    - id: N-001\n"
    "      desc: <한 줄 비기능 요구 — 성능·접근성·배포 형태 등>\n"
    "      priority: <must | should | could>\n"
    "  assumptions:                # 사용자 요청에 없어 본 단계에서 임의로 채운 가정\n"
    "    - <한 줄 가정 + 출처(왜 그렇게 가정했는지 한 단어)>\n"
    "  open_questions:             # 답이 없으면 BLOCKED 가능성 — 결정적 미해결 질문\n"
    "    - <한 줄 질문>\n"
    "  ```\n"
    "\n"
    "  ## 분석가 노트\n"
    "    - 핵심 가정 1~2건과 그 영향 (왜 이렇게 가정했고 어디로 흐름을 좁혔는지)\n"
    "    - 가장 위험한 open_question 1건 — 이게 풀리지 않으면 무엇이 막히는가\n"
    "\n"
    "**출력 규약 (CRITICAL)**: `Final Answer:` 라인에 한 줄 요약 (`spec expanded "
    "with <F>개 functional, <N>개 nonfunctional, <a>개 assumptions, <o>개 "
    "open_questions`) 을 두고, **그 다음 줄부터 위 모든 본문 섹션** (## 명세 YAML + "
    "## 분석가 노트) 을 작성하세요. 본문이 `Final Answer:` 보다 **앞** 에 오면 "
    "CrewAI 가 본문을 잃어버려 후속 단계가 functional/nonfunctional 명세를 받지 "
    "못합니다 (이슈 4 회귀).\n\n"
    "정확한 출력 형태:\n"
    "```\n"
    "Thought: <간단한 사고 한 줄>\n"
    "Final Answer: spec expanded with 5개 functional, 2개 nonfunctional, 3개 assumptions, 1개 open_questions\n"
    "\n"
    "## 명세\n"
    "<본문 YAML>\n"
    "\n"
    "## 분석가 노트\n"
    "<본문>\n"
    "```\n\n"
    "중요: 당신은 *해석자가 아니라 정리자* 입니다. 사용자가 적지 않은 것을 "
    "코드 레벨까지 결정하지 마세요. 그것은 CTO·Engineer 의 역할입니다. 당신의 "
    "유일한 산출은 위 2단 구조이며, *무엇을 만들지* 의 윤곽만 분명히 하면 됩니다."
)


def create_requirement_expander_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = True,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> Agent:
    """Nexus Alpha 의 Requirement Expander 에이전트를 생성해 반환한다.

    Args:
        llm: 사용할 LLM 어댑터. 기본값은 새로운 `NexusAlphaLLM()` 인스턴스.
            테스트·커스터마이징 목적에서만 명시적으로 주입한다.
        verbose: CrewAI 의 중간 사고 과정을 콘솔에 출력할지 여부.
            운영 환경에서는 False 를 권장.
        max_iter: 에이전트가 한 태스크당 반복 가능한 최대 횟수.
            요구 정리는 1회 추론으로 충분하므로 기본 3회로 안전.
        allow_delegation: 다른 에이전트로 작업을 위임할 수 있는지 여부.
            본 단계는 단독 추론 원칙으로 False.

    Returns:
        구성이 완료된 CrewAI `Agent` 인스턴스.

    Raises:
        RuntimeError: `NexusAlphaLLM` 초기화 단계에서 Provider 생성에
            실패한 경우 (예: API Key 모드인데 키 누락).
    """
    if llm is None:
        llm = NexusAlphaLLM()

    return Agent(
        name=REQUIREMENT_EXPANDER_NAME,
        role=REQUIREMENT_EXPANDER_ROLE,
        goal=REQUIREMENT_EXPANDER_GOAL,
        backstory=REQUIREMENT_EXPANDER_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )
