import { useCallback, useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

import { BoardroomPanel } from './components/BoardroomPanel'
import { RunReportPanel } from './components/RunReportPanel'

// =============================================================================
// Sprint 6 — Agent Office (조직도 v12 11 본부 + 54 멤버 + UI polish)
// =============================================================================
//
// 본 file 은 docs/architecture/Nexus_Alpha_조직도_v12.md 의 11 본부 + 54 멤버
// 정의를 그대로 반영. 본 PR 의 추가 UI 강화:
//   1. 상단 통계바 (ACTIVE/IDLE/미구현/전체 + 실행 노드 + telemetry counts)
//   2. 부서 필터 버튼 (전체 + 10 본부)
//   3. 우측 패널 220→280px + 모델/도구/파이프라인 + 대화 expand/collapse
//   4. ACTIVE 카드 펄스 + 큰 ACTIVE 뱃지 + 미구현 자물쇠
//   5. 호버 툴팁 강화 (모델/도구수/파이프라인)
//
// 백엔드 코드 변경 0.

// =============================================================================
// 1. 타입 정의
// =============================================================================

type HQKey =
  | 'hq-0'
  | 'hq-1'
  | 'hq-2'
  | 'hq-3'
  | 'hq-4'
  | 'hq-5'
  | 'hq-6'
  | 'hq-7'
  | 'hq-8'
  | 'hq-9'
  | 'hq-10'

type ModelTier = 'opus' | 'sonnet' | 'haiku' | 'tbd'

interface AgentInfo {
  name: string
  role: string
  goalDetailed?: string
  implemented: boolean
  hq: HQKey
  model?: ModelTier
  tools?: string[]
  pipelines?: string[]
  /**
   * v13 PR #228 — 부서 대표 (이사회 참석자) 표시.
   * true 면 카드에 👑 + 금색 테두리 + 밝은 틴트 (3중 시각 표시).
   * 명단 = DEFAULT_BOARDROOM_ATTENDEES (boardroom_facilitator.py) +
   * 각 본부 리드 1명 (조직도 v13 명시 없을 시 fallback).
   * 미구현 (implemented=false) 에이전트는 본 필드 true 라도 왕관 미표시.
   */
  is_representative?: boolean
}

interface HeadquartersDef {
  key: HQKey
  no: number
  label: string
  filterLabel: string
  borderClass: string
  bgClass: string
  accentClass: string
  charBgClass: string
  pulseRgba: string
  defaultModel: ModelTier
  defaultTools: string[]
  defaultPipelines: string[]
  agents: AgentInfo[]
}

const HEADQUARTERS: HeadquartersDef[] = [
  {
    key: 'hq-0',
    no: 0,
    label: 'C-Level',
    filterLabel: 'C-Level',
    borderClass: 'border-amber-500/60',
    bgClass: 'bg-amber-950/20',
    accentClass: 'text-amber-300',
    charBgClass: 'bg-amber-300',
    pulseRgba: 'rgba(245, 158, 11, 0.5)',
    defaultModel: 'opus',
    defaultTools: ['decision_record', 'Read', 'Grep'],
    defaultPipelines: ['Track A', 'Track B'],
    agents: [
      {
        name: 'CTO',
        role: 'Chief Technology Officer — 기술 전략',
        goalDetailed:
          '기술 전략 + 아키텍처 결정 + 기술 스택 선택. run_chain 노드의 첫 LLM 호출 주체. 단일 페이지 vs 다중 모듈, framework 선택 등 거시 결정 담당.',
        implemented: true,
        hq: 'hq-0',
        model: 'opus',
        tools: ['decision_record', 'architectural_pattern_db', 'Read'],
        pipelines: ['Track A', 'Track B'],
        is_representative: true,
      },
      {
        name: 'Goal Alignment Agent',
        role: 'v13 ⭐ 이사회 의장 — 시스템 목적 + 보안 거버넌스 최종 조율',
        goalDetailed:
          'v13 ⭐ (이전 CEO) Boardroom 이사회의 의장 역임. 시스템의 궁극적 목적 + 보안 거버넌스 최종 조율. Telemetry 기반 자율 진화 안건의 *목적 부합 여부* 최종 판정. Phase 4 (PR #222) 구현 — forbidden 키워드 (한/영 13건) 결정론 + LLM 옵션 → approved/rejected.',
        implemented: true,
        hq: 'hq-0',
        tools: ['assess_alignment', 'decision_record', 'Read'],
        is_representative: true,
      },
      {
        name: 'Token Budget Optimizer',
        role: 'v13 ⭐ 기술재무관 — LLM 비용 + 컴퓨팅 자원 한도 브레이크',
        goalDetailed:
          'v13 ⭐ (이전 CFO) Boardroom 이사회의 기술재무관. LLM 호출 비용 + 컴퓨팅 자원 한도 기반 *브레이크* 역할. 자율 진화 안건의 토큰 견적 + 예산 한도 검증. Phase 4 (PR #222) 구현 — tier 매핑 (low/medium/high → 0.5/2.0/10.0 USD) + 한도 env (default $15) + 누적 비용 (events.jsonl Opus 4.7 단가) → approved/throttled.',
        implemented: true,
        hq: 'hq-0',
        tools: ['assess_budget', 'decision_record', 'Read'],
        is_representative: true,
      },
    ],
  },
  {
    key: 'hq-1',
    no: 1,
    label: '업무 분석',
    filterLabel: '업무 분석',
    borderClass: 'border-sky-500/60',
    bgClass: 'bg-sky-950/25',
    accentClass: 'text-sky-300',
    charBgClass: 'bg-sky-300',
    pulseRgba: 'rgba(14, 165, 233, 0.5)',
    defaultModel: 'sonnet',
    defaultTools: ['Read', 'Grep', 'yaml_writer'],
    defaultPipelines: ['Track A', 'Track B'],
    agents: [
      {
        name: 'Requirement Expander',
        role: '사용자 요청 YAML 확장',
        goalDetailed:
          'expand_requirements 노드에서 호출. 자연어 → 5필드 YAML (goal/inputs/outputs/constraints/acceptance_criteria) 로 *결정론적* 확장.',
        implemented: true,
        hq: 'hq-1',
        is_representative: true,
      },
      {
        name: 'Gap Analyst',
        role: 'iteration feedback gap 분석',
        goalDetailed:
          'analyze_gap 노드. 이전 iteration 의 retrospective + executor_result + qa_review 를 종합하여 *다음 iter 의 개선 지시* 산출.',
        implemented: true,
        hq: 'hq-1',
      },
      {
        name: 'Data Analyst',
        role: 'Track B 분석 + instruction',
        goalDetailed:
          'Track B 의 run_chain 진입점. 도메인 분석 + 입력 데이터 schema 파악 + Specialist agent 에게 전달할 instruction 작성.',
        implemented: true,
        hq: 'hq-1',
        pipelines: ['Track B'],
      },
      {
        name: 'System Refactoring Strategist',
        role: 'v13 ⭐ 런타임 + Telemetry 분석 → 이사회 자율 개선안 안건 발제',
        goalDetailed:
          'v13 ⭐ 자기 진화 루프의 *안건 발제* 노드. 런타임 로그 + Telemetry 데이터를 분석해 시스템 자율 개선안 (예: max_iterations 상향 / GUI sandbox SKIP 강화 / Token 한도 조정) 을 Boardroom 에 안건으로 제출. v12 의 Business Process Analyst + Use Case Specialist 삭제 (행정 오버헤드 다이어트) 후 자율 진화 차원으로 신설. Phase 2 구현 — Auto-Fix Coordinator escalate hook 활용, --enable-strategist opt-in.',
        implemented: true,
        hq: 'hq-1',
        is_representative: true,
      },
    ],
  },
  {
    key: 'hq-2',
    no: 2,
    label: '기획 및 설계',
    filterLabel: '기획·설계',
    borderClass: 'border-violet-500/60',
    bgClass: 'bg-violet-950/25',
    accentClass: 'text-violet-300',
    charBgClass: 'bg-violet-300',
    pulseRgba: 'rgba(139, 92, 246, 0.5)',
    defaultModel: 'sonnet',
    defaultTools: ['Read', 'mockup_generator'],
    defaultPipelines: ['Track A'],
    agents: [
      {
        name: 'UI/UX Analyst',
        role: 'UI/UX 명세 + 권장 framework',
        goalDetailed:
          'Track A 의 GUI 분기에서 호출. 사용자 인터페이스 요구 분석 + Tkinter/Flet/PyQt6 중 추천 + widget 트리 outline.',
        implemented: true,
        hq: 'hq-2',
        pipelines: ['Track A GUI'],
        is_representative: true,
      },
      {
        name: 'Product Manager',
        role: '제품 전략 (미구현)',
        implemented: false,
        hq: 'hq-2',
      },
    ],
  },
  {
    key: 'hq-3',
    no: 3,
    label: '개발 (Track A + B)',
    filterLabel: 'ENGINEERING',
    borderClass: 'border-emerald-500/60',
    bgClass: 'bg-emerald-950/25',
    accentClass: 'text-emerald-300',
    charBgClass: 'bg-emerald-300',
    pulseRgba: 'rgba(16, 185, 129, 0.5)',
    defaultModel: 'sonnet',
    defaultTools: ['Edit', 'Write', 'Bash', 'Read', 'Glob', 'Grep'],
    defaultPipelines: ['Track A', 'Track B'],
    agents: [
      {
        name: 'Python Engineer',
        role: 'Senior Python — Track A 핵심',
        goalDetailed:
          'Track A 의 메인 코드 생성자. CTO 의 결정 + UI/UX Analyst 의 명세 + Code Reviewer 의 피드백을 받아 *full 모듈* 코드를 산출.',
        implemented: true,
        hq: 'hq-3',
        model: 'opus',
        pipelines: ['Track A'],
        is_representative: true,
      },
      {
        name: 'Web Scraping Specialist',
        role: 'Playwright/Selenium (Track B)',
        goalDetailed: 'Web 페이지 자동화. robots.txt 검토 + rate limit jitter + selector 전략.',
        implemented: true,
        hq: 'hq-3',
        tools: ['playwright', 'selenium', 'beautifulsoup'],
        pipelines: ['Track B'],
      },
      {
        name: 'API Integration Developer',
        role: 'REST/GraphQL (Track B)',
        goalDetailed: 'API 통합. httpx + tenacity + Pydantic 검증 + secret 환경변수.',
        implemented: true,
        hq: 'hq-3',
        tools: ['httpx', 'tenacity', 'pydantic'],
        pipelines: ['Track B'],
      },
      {
        name: 'Data Parser Engineer',
        role: 'Excel/PDF/CSV (Track B)',
        goalDetailed: 'openpyxl + pdfplumber + chardet (cp949 fallback) + structured output.',
        implemented: true,
        hq: 'hq-3',
        tools: ['openpyxl', 'pdfplumber', 'chardet'],
        pipelines: ['Track B'],
      },
      {
        name: 'Desktop Automation Specialist',
        role: 'PyAutoGUI/PyWinAuto (Track B)',
        goalDetailed: 'Windows native UI 자동화. UIA selector + FAILSAFE 모드.',
        implemented: true,
        hq: 'hq-3',
        tools: ['pyautogui', 'pywinauto'],
        pipelines: ['Track B'],
      },
      {
        name: 'DevOps Engineer',
        role: 'Docker/CI/CD (Track B)',
        goalDetailed: 'Dockerfile multi-stage + GitHub Actions workflow + matrix Python 3.11~3.13.',
        implemented: true,
        hq: 'hq-3',
        tools: ['docker', 'github_actions'],
        pipelines: ['Track B'],
      },
      {
        name: 'Mobile Developer',
        role: '모바일 (미구현, Phase 9)',
        implemented: false,
        hq: 'hq-3',
      },
      {
        name: 'Embedded Specialist',
        role: '임베디드 (미구현, Phase 9)',
        implemented: false,
        hq: 'hq-3',
      },
    ],
  },
  {
    key: 'hq-4',
    no: 4,
    label: '품질 검증',
    filterLabel: 'QA',
    borderClass: 'border-red-500/60',
    bgClass: 'bg-red-950/25',
    accentClass: 'text-red-300',
    charBgClass: 'bg-red-300',
    pulseRgba: 'rgba(239, 68, 68, 0.5)',
    defaultModel: 'sonnet',
    defaultTools: ['pytest', 'ruff', 'code_qa_executor'],
    defaultPipelines: ['Track A', 'Track B', 'Build'],
    agents: [
      {
        name: 'Code Reviewer',
        role: 'Senior Code Reviewer (Static QA)',
        goalDetailed:
          'run_chain 내부 — Python Engineer 의 산출 코드를 *Pydantic schema + 5단 본문* 으로 검토.',
        implemented: true,
        hq: 'hq-4',
        is_representative: true,
      },
      {
        name: 'Pytest Author',
        role: 'Test 생성 + 검증',
        goalDetailed:
          'pytest_suite 생성. 4 카테고리 (Happy/Edge/Load/Error) 분포 + ≥1200 chars 분량 임계.',
        implemented: true,
        hq: 'hq-4',
      },
      {
        name: 'Code QA',
        role: 'pytest + ruff 실행',
        goalDetailed: 'code_qa_executor 가 pytest + ruff 자동 실행, exit code 기반 verdict.',
        implemented: true,
        hq: 'hq-4',
        tools: ['pytest', 'ruff'],
      },
      {
        name: 'Functional Test Agent',
        role: 'Functional 테스트 suite',
        implemented: true,
        hq: 'hq-4',
      },
      {
        name: 'GUI Test Agent',
        role: 'pyautogui + Vision QA',
        goalDetailed: 'GUI 앱의 자동 클릭 + 스크린샷 + LLM Vision 검증.',
        implemented: true,
        hq: 'hq-4',
        tools: ['pyautogui', 'vision_llm'],
      },
      {
        name: 'Performance Engineer',
        role: 'Performance / profiling',
        implemented: true,
        hq: 'hq-4',
      },
      {
        name: 'Security Auditor',
        role: '취약점 스캔',
        implemented: true,
        hq: 'hq-4',
      },
      {
        name: 'Compliance Officer',
        role: '규정 검증',
        implemented: true,
        hq: 'hq-4',
      },
      {
        name: 'Robustness Tester',
        role: 'Chaos / edge case',
        implemented: true,
        hq: 'hq-4',
      },
      {
        name: 'Convergence Judge',
        role: '결정론 verdict (c_level 디렉터리)',
        goalDetailed:
          'judge_convergence 노드. COMPLETE/IMPROVE_NEEDED/BLOCKED 중 *결정론적* 판정 (LLM X). 4 rule (qa_pass / max_iter / budget / must_fix).',
        implemented: true,
        hq: 'hq-4',
        model: 'opus',
        tools: ['decision_rules'],
      },
    ],
  },
  {
    key: 'hq-5',
    no: 5,
    label: '지식 관리',
    filterLabel: 'LEARNING',
    borderClass: 'border-teal-500/60',
    bgClass: 'bg-teal-950/25',
    accentClass: 'text-teal-300',
    charBgClass: 'bg-teal-300',
    pulseRgba: 'rgba(20, 184, 166, 0.5)',
    defaultModel: 'haiku',
    defaultTools: ['yaml_writer', 'rag_index'],
    defaultPipelines: ['공통'],
    agents: [
      {
        name: 'Knowledge Curator',
        role: 'YAML 인덱싱',
        goalDetailed:
          'curate_knowledge 노드. workflow_dir 의 산출물을 knowledge_entry.yaml 로 큐레이션 + outputs/_index.yaml 누적.',
        implemented: true,
        hq: 'hq-5',
        is_representative: true,
      },
      {
        name: 'RAG Searcher',
        role: '과거 workflow recall',
        goalDetailed:
          'recall_past_knowledge 노드. knowledge_index 에서 유사 과거 workflow 검색 → SharedKickoffDecisions 주입.',
        implemented: true,
        hq: 'hq-5',
      },
      {
        name: 'Documentation Lead',
        role: '문서 관리 (미구현)',
        implemented: false,
        hq: 'hq-5',
      },
    ],
  },
  {
    key: 'hq-6',
    no: 6,
    label: '운영 지원',
    filterLabel: '운영',
    borderClass: 'border-slate-500/60',
    bgClass: 'bg-slate-800/30',
    accentClass: 'text-slate-300',
    charBgClass: 'bg-slate-300',
    pulseRgba: 'rgba(148, 163, 184, 0.5)',
    defaultModel: 'sonnet',
    defaultTools: ['subprocess', 'file_io'],
    defaultPipelines: ['Track A', 'Track B', 'sandbox'],
    agents: [
      {
        name: 'Sandbox Runner',
        role: '격리 subprocess 실행',
        goalDetailed:
          'run_sandbox 노드. 산출 코드를 *격리 subprocess* 에서 timeout 보호 실행. LLM 호출 없음 — *결정론 executor*.',
        implemented: true,
        hq: 'hq-6',
        model: 'tbd',
        tools: ['subprocess', 'timeout_guard'],
        is_representative: true,
      },
      {
        name: 'Monitoring Engineer',
        role: '모니터링 (미구현)',
        implemented: false,
        hq: 'hq-6',
      },
    ],
  },
  {
    key: 'hq-7',
    no: 7,
    label: '디자인',
    filterLabel: 'DESIGN',
    borderClass: 'border-pink-500/60',
    bgClass: 'bg-pink-950/25',
    accentClass: 'text-pink-300',
    charBgClass: 'bg-pink-300',
    pulseRgba: 'rgba(236, 72, 153, 0.5)',
    defaultModel: 'sonnet',
    defaultTools: ['Tkinter', 'Flet', 'PyQt6'],
    defaultPipelines: ['Track A GUI'],
    agents: [
      {
        name: 'GUI Code Generator',
        role: 'Tkinter/Flet/PyQt6 코드',
        goalDetailed:
          'enable_gui_branch 시 호출. UI/UX Analyst 의 명세를 받아 *실제 widget 트리 코드* 생성. mockup vs 실제 일치 검증 대상.',
        implemented: true,
        hq: 'hq-7',
        is_representative: true,
      },
      {
        name: 'GUI Designer',
        role: '와이어프레임 + widget tree',
        implemented: true,
        hq: 'hq-7',
      },
      {
        name: 'Theme Designer',
        role: 'Design tokens',
        implemented: true,
        hq: 'hq-7',
      },
    ],
  },
  {
    key: 'hq-8',
    no: 8,
    label: '빌드 & 배포',
    filterLabel: 'BUILD & RELEASE',
    borderClass: 'border-lime-500/60',
    bgClass: 'bg-lime-950/25',
    accentClass: 'text-lime-300',
    charBgClass: 'bg-lime-300',
    pulseRgba: 'rgba(132, 204, 22, 0.5)',
    defaultModel: 'sonnet',
    defaultTools: ['PyInstaller', 'gh_cli'],
    defaultPipelines: ['Build', 'Release'],
    agents: [
      {
        name: 'Build Engineer',
        role: 'PyInstaller .exe',
        goalDetailed:
          '`pyinstaller` 호출 orchestration. dependency 분석 + entry 결정 + collect-all hitlist + 2단계 pre-PyInstaller validation.',
        implemented: true,
        hq: 'hq-8',
        is_representative: true,
      },
      { name: 'Asset Manager', role: 'Binary packaging', implemented: true, hq: 'hq-8' },
      { name: 'Changelog Generator', role: 'Release notes', implemented: true, hq: 'hq-8' },
      { name: 'Dependency Analyzer', role: 'Dep security scan', implemented: true, hq: 'hq-8' },
      { name: 'Distribution Agent', role: 'Distribution 전략', implemented: true, hq: 'hq-8' },
      { name: 'Installer Creator', role: 'NSIS Windows installer', implemented: true, hq: 'hq-8' },
      { name: 'Platform Tester', role: 'Multi-platform 테스트', implemented: true, hq: 'hq-8' },
      {
        name: 'Release Manager',
        role: 'GitHub release',
        goalDetailed: '`gh release create` orchestration. SHA256 + Draft / Published 토글.',
        implemented: true,
        hq: 'hq-8',
        tools: ['gh_cli', 'sha256'],
      },
      { name: 'Update Checker', role: 'Version 관리', implemented: true, hq: 'hq-8' },
    ],
  },
  {
    key: 'hq-9',
    no: 9,
    label: 'Runtime Verification',
    filterLabel: 'RV',
    borderClass: 'border-orange-500/60',
    bgClass: 'bg-orange-950/25',
    accentClass: 'text-orange-300',
    charBgClass: 'bg-orange-300',
    pulseRgba: 'rgba(249, 115, 22, 0.5)',
    defaultModel: 'opus',
    defaultTools: ['psutil', 'pyautogui', 'playwright'],
    defaultPipelines: ['RV'],
    agents: [
      {
        name: 'Exe Runtime Tester',
        role: '.exe sandbox 실행 검증 (Phase A)',
        goalDetailed: '빌드된 .exe 의 시작시간/exit/stderr/메모리 peak 측정. Phase A 1순위.',
        implemented: true,
        hq: 'hq-9',
      },
      {
        name: 'UI Automation Specialist',
        role: 'PyAutoGUI/Playwright (Phase B)',
        implemented: true,
        hq: 'hq-9',
      },
      {
        name: 'Runtime Failure Analyzer',
        role: '실행 fail trace 분석 (Phase C)',
        implemented: true,
        hq: 'hq-9',
      },
      {
        name: 'Auto-Fix Coordinator',
        role: 'RV 재빌드 trigger (Phase C)',
        implemented: true,
        hq: 'hq-9',
        is_representative: true,
      },
    ],
  },
  {
    key: 'hq-10',
    no: 10,
    label: 'Coordination',
    filterLabel: 'Coordination',
    borderClass: 'border-purple-500/60',
    bgClass: 'bg-purple-950/25',
    accentClass: 'text-purple-300',
    charBgClass: 'bg-purple-300',
    pulseRgba: 'rgba(168, 85, 247, 0.5)',
    defaultModel: 'opus',
    defaultTools: ['LangGraph_state', 'shared_context_pool'],
    defaultPipelines: ['공통'],
    agents: [
      {
        name: 'Boardroom Facilitator',
        role: 'v13 ⭐ Telemetry 기반 전략 이사회 의장 (집단 지성 티키타카 리드)',
        goalDetailed:
          'v13 ⭐ kickoff_meeting 노드의 v12 Meeting Facilitator 가 v13 에서 격상. 단순 행정 회의가 아니라 C-Level (Goal Alignment + Token Budget + CTO) + 부서 대표 에이전트들이 모여 Telemetry 기반 시스템 개선안을 *치열하게 토론* + *타협점 도출* 하는 전략 이사회 프로세스 리드. 자율 진화 루프의 의장 노드.',
        implemented: true,
        hq: 'hq-10',
        is_representative: true,
      },
      {
        name: 'Retrospective Lead',
        role: '4-step 회고',
        goalDetailed:
          'retrospective 노드. well_done / went_wrong / lessons_learned / kickoff_delta 4 카테고리 회고 YAML.',
        implemented: true,
        hq: 'hq-10',
      },
      {
        name: 'Cross-Agent Consultant',
        role: '양방향 라우팅 (미구현, Phase 2)',
        implemented: false,
        hq: 'hq-10',
      },
      {
        name: 'Knowledge Curator (promoted)',
        role: 'v11 Phase 3 — 본부 5 의 Knowledge Curator 가 본부 10 으로 조직개편된 인스턴스 (구현 ✅ — agent 자체는 본부 5 의 curator.py)',
        goalDetailed:
          'Knowledge Curator agent 자체는 본부 5 에 *이미 구현* (knowledge/curator.py). 본부 10 의 "(promoted)" 는 *조직 개편 차원의 논리적 매핑* — 동일 agent 가 본부 10 desk 도 갖는 v11 Phase 3 비전. agent 인스턴스 실재 → implemented: true.',
        implemented: true,
        hq: 'hq-10',
      },
    ],
  },
]

const NODE_TO_HQS: Record<string, HQKey[]> = {
  expand_requirements: ['hq-1'],
  kickoff_meeting: ['hq-10'],
  analyze_gap: ['hq-1'],
  prepare_feedback: [],
  run_chain: ['hq-0', 'hq-3', 'hq-4'],
  run_sandbox: ['hq-6'],
  recall_past_knowledge: ['hq-5'],
  judge_convergence: ['hq-4'],
  retrospective: ['hq-10'],
  retrospective_blocked: ['hq-10'],
  curate_knowledge: ['hq-5'],
  curate_knowledge_blocked: ['hq-5'],
  finalize: [],
  escalate: [],
}

interface TelemetryEvent {
  type?: string
  agent?: string
  department?: string
  status?: string
  phase?: string
  verdict?: string
  ts?: string
  kind?: string
  path?: string
  detail?: string
  role?: string
  prompt_preview?: string
  output_preview?: string
  // P20 — checkpoint 이벤트 필드 (type === 'checkpoint')
  plan_summary?: string
  timeout_sec?: number
  intervention_file?: string
  checkpoint_id?: string
  node?: string
  // P22 — iter 간 개입: 패널 분기(iteration>=2) + '빌드 열어보기' 대상(직전 빌드 경로).
  iteration?: number
  prev_build_path?: string
  [k: string]: unknown
}

interface CapturedLine {
  raw: string
  parsed: TelemetryEvent | null
  receivedAt: string
}

interface AuthStatus {
  loggedIn: boolean
  email: string | null
  subscriptionType: string | null
  authMethod: string | null
  orgName: string | null
  error: string | null
}

const EMPTY_AUTH: AuthStatus = {
  loggedIn: false,
  email: null,
  subscriptionType: null,
  authMethod: null,
  orgName: null,
  error: null,
}

const MAX_LINES = 200
const MAX_MESSAGES = 80

type MenuKey =
  | 'agent-map'
  | 'boardroom'
  | 'run-report'
  | 'system'
  | 'monitor'
  | 'catalog'
  | 'usage'
  | 'settings'

interface MenuItem {
  key: MenuKey
  label: string
  enabled: boolean
}

const MENU_ITEMS: MenuItem[] = [
  { key: 'agent-map', label: '에이전트 맵', enabled: true },
  // v13 Phase 5.1 (PR #223) — Boardroom panel + decision.yaml viewer
  { key: 'boardroom', label: '이사회 의결', enabled: true },
  // v13 P21 — 런 산출물 본부별 리포트 + PDF/HTML/zip 다운로드 (읽기 전용)
  { key: 'run-report', label: '런 리포트', enabled: true },
  { key: 'system', label: '시스템 개요', enabled: false },
  { key: 'monitor', label: '실시간 모니터', enabled: false },
  { key: 'catalog', label: '카탈로그', enabled: false },
  { key: 'usage', label: '사용 통계', enabled: false },
  { key: 'settings', label: '설정', enabled: false },
]

type FilterKey = 'all' | HQKey

// P18 — 빌드 타깃: web(vite→dist 기본) / desktop(PyInstaller .exe) / none(빌드 없음).
type BuildTarget = 'web' | 'desktop' | 'none'

// =============================================================================
// 2. PixelCharacter
// =============================================================================

const FACE_PATTERN = [
  '0011110000111100',
  '0111111001111110',
  '1111111111111111',
  '1111111111111111',
  '1100110011001100',
  '1100110011001100',
  '1111111111111111',
  '1111111111111111',
  '1111111111111111',
  '1110000000000111',
  '1111000000001111',
  '1111111111111111',
  '1111111111111111',
  '0111111111111110',
  '0011111111111100',
  '0000111111110000',
].map((row) => row.split(''))

interface PixelCharacterProps {
  bgClass: string
  bobbing: boolean
  faded: boolean
}

function PixelCharacter({ bgClass, bobbing, faded }: PixelCharacterProps) {
  const effectiveBg = faded ? 'bg-slate-600' : bgClass
  return (
    <div
      className={`w-7 h-7 ${bobbing ? 'animate-bob' : ''} ${faded ? 'opacity-50 grayscale' : ''}`}
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(16, minmax(0, 1fr))',
        gridTemplateRows: 'repeat(16, minmax(0, 1fr))',
      }}
      aria-hidden
    >
      {FACE_PATTERN.flat().map((cell, i) => (
        <div key={i} className={cell === '1' ? effectiveBg : ''} />
      ))}
    </div>
  )
}

// =============================================================================
// 3. helpers
// =============================================================================

// P18 — max-iterations 입력(문자열) → run.py 로 보낼 1~10 정수로 정규화.
// 빈 입력/비정상은 기본 3 으로 복원, 그 외는 1~10 클램프. 입력 중에는 문자열 state 로
// 자유 타이핑(일시적 빈 값 포함) 허용하고, 제출/blur 시점에 본 함수로 확정.
function clampMaxIterations(raw: string): number {
  const n = Math.round(Number(raw))
  if (!Number.isFinite(n) || raw.trim() === '') return 3
  return Math.min(10, Math.max(1, n))
}

// P19 — 산출물이 web(.html) 인지 (▶실행 분기용 — Rust open_exe 와 동일 신호).
function isWebArtifact(path?: string | null): boolean {
  return !!path && /\.html?$/i.test(path)
}

function effectiveModel(agent: AgentInfo, hq: HeadquartersDef): ModelTier {
  return agent.model ?? hq.defaultModel
}
function effectiveTools(agent: AgentInfo, hq: HeadquartersDef): string[] {
  return agent.tools ?? hq.defaultTools
}
function effectivePipelines(agent: AgentInfo, hq: HeadquartersDef): string[] {
  return agent.pipelines ?? hq.defaultPipelines
}

const TOTAL_AGENTS = HEADQUARTERS.reduce((sum, h) => sum + h.agents.length, 0)
const IMPLEMENTED_AGENTS = HEADQUARTERS.reduce(
  (sum, h) => sum + h.agents.filter((a) => a.implemented).length,
  0,
)
const UNIMPLEMENTED_AGENTS = TOTAL_AGENTS - IMPLEMENTED_AGENTS

// =============================================================================
// 4. App
// =============================================================================

function App() {
  const [request, setRequest] = useState('')
  const [running, setRunning] = useState(false)
  const [eventsPath, setEventsPath] = useState<string | null>(null)
  const [lines, setLines] = useState<CapturedLine[]>([])
  const [error, setError] = useState<string | null>(null)
  const [auth, setAuth] = useState<AuthStatus>(EMPTY_AUTH)
  const [authLoading, setAuthLoading] = useState<boolean>(true)
  const [activeHqs, setActiveHqs] = useState<Set<HQKey>>(new Set())
  const [currentNodeByHq, setCurrentNodeByHq] = useState<Record<string, string>>({})
  const [selectedAgent, setSelectedAgent] = useState<AgentInfo | null>(null)
  const [activeMenu, setActiveMenu] = useState<MenuKey>('agent-map')
  const [filter, setFilter] = useState<FilterKey>('all')
  const [agentMessages, setAgentMessages] = useState<TelemetryEvent[]>([])
  const [expandedMsg, setExpandedMsg] = useState<Set<number>>(new Set())
  // P18 — 런 옵션을 PowerShell(run.py)과 동등하게: 빌드 타깃 / max-iterations / 토글.
  const [buildTarget, setBuildTarget] = useState<BuildTarget>('web')
  // 문자열 state 로 자유 타이핑 허용 (clampMaxIterations 가 제출/blur 시 1~10 확정).
  const [maxIterStr, setMaxIterStr] = useState<string>('3')
  const [autoIterate, setAutoIterate] = useState<boolean>(true)
  const [enableTechScout, setEnableTechScout] = useState<boolean>(true)
  // P20 — 런 중 사람 개입 체크포인트 (기본 OFF). ON 이면 --intervene 전달.
  const [interveneEnabled, setInterveneEnabled] = useState<boolean>(false)
  const [checkpoint, setCheckpoint] = useState<TelemetryEvent | null>(null)
  const [checkpointFeedback, setCheckpointFeedback] = useState<string>('')
  const [checkpointRemaining, setCheckpointRemaining] = useState<number>(0)
  const [resultEvent, setResultEvent] = useState<TelemetryEvent | null>(null)
  const [exeRunMessage, setExeRunMessage] = useState<string | null>(null)

  const refreshAuth = useCallback(async () => {
    setAuthLoading(true)
    try {
      const status = await invoke<AuthStatus>('claude_auth_status')
      setAuth(status)
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[Auth] status 조회 실패', e)
      setAuth({ ...EMPTY_AUTH, error: String(e ?? 'unknown') })
    } finally {
      setAuthLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshAuth()
  }, [refreshAuth])

  useEffect(() => {
    let unlisten: UnlistenFn | undefined
    listen<string>('nexus://telemetry', (event) => {
      const raw = String(event.payload ?? '')
      let parsed: TelemetryEvent | null = null
      try {
        parsed = JSON.parse(raw) as TelemetryEvent
      } catch {
        parsed = null
      }
      // eslint-disable-next-line no-console
      console.log('[Telemetry]', parsed?.type ?? 'unknown', parsed ?? raw)

      setLines((prev) => {
        const captured: CapturedLine = { raw, parsed, receivedAt: new Date().toISOString() }
        const next = [...prev, captured]
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next
      })

      if (parsed?.type === 'agent_status' && parsed.agent) {
        const hqs = NODE_TO_HQS[parsed.agent] ?? []
        if (hqs.length > 0) {
          if (parsed.status === 'working') {
            setActiveHqs((prev) => {
              const next = new Set(prev)
              hqs.forEach((h) => next.add(h))
              return next
            })
            setCurrentNodeByHq((prev) => {
              const next = { ...prev }
              hqs.forEach((h) => {
                next[h] = parsed.agent!
              })
              return next
            })
          } else if (parsed.status === 'done' || parsed.status === 'error') {
            setActiveHqs((prev) => {
              const next = new Set(prev)
              hqs.forEach((h) => next.delete(h))
              return next
            })
            setCurrentNodeByHq((prev) => {
              const next = { ...prev }
              hqs.forEach((h) => {
                if (next[h] === parsed.agent) delete next[h]
              })
              return next
            })
          }
        }
      }

      if (parsed?.type === 'agent_message') {
        setAgentMessages((prev) => {
          const next = [...prev, parsed]
          return next.length > MAX_MESSAGES ? next.slice(-MAX_MESSAGES) : next
        })
      }

      if (parsed?.type === 'result') {
        // 빌드된 .exe 경로 보존 — banner + 실행 버튼용
        setResultEvent(parsed)
      }
      // P20 — codegen 직전 개입 체크포인트: 패널 표시 + 카운트다운 시작.
      if (parsed?.type === 'checkpoint') {
        setCheckpoint(parsed)
        setCheckpointFeedback('')
        // P22 — 순차 체크포인트(iter1→2→3) 간 직전 '빌드 열어보기' 메시지 잔존 방지.
        setExeRunMessage(null)
        setCheckpointRemaining(Number(parsed.timeout_sec) || 90)
      }
      if (
        parsed?.type === 'result' ||
        (parsed?.type === 'iteration_progress' && parsed.phase === 'run_end')
      ) {
        setRunning(false)
        setActiveHqs(new Set())
        setCurrentNodeByHq({})
        // 런 종료 시 잔존 체크포인트 패널 닫기 (안전).
        setCheckpoint(null)
      }
    })
      .then((fn) => {
        unlisten = fn
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('[Telemetry] listen 등록 실패', err)
      })
    return () => {
      unlisten?.()
    }
  }, [])

  // P20 — 체크포인트 카운트다운. 패널이 열려 있으면 1초마다 남은 시간 감소, 0 이면 자동 닫힘
  // (하네스도 동일 타임아웃으로 자동 진행). 패널이 바뀌거나 닫히면 타이머 정리.
  useEffect(() => {
    if (!checkpoint) return
    const id = setInterval(() => {
      setCheckpointRemaining((prev) => {
        if (prev <= 1) {
          setCheckpoint(null) // 타임아웃 — 패널 닫힘, 런은 하네스가 자동 진행
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(id)
  }, [checkpoint])

  const counts = useMemo(() => {
    const acc: Record<string, number> = {
      agent_status: 0,
      agent_message: 0,
      iteration_progress: 0,
      result: 0,
      tail_meta: 0,
      unknown: 0,
    }
    for (const line of lines) {
      const t = line.parsed?.type ?? 'unknown'
      acc[t] = (acc[t] ?? 0) + 1
    }
    return acc
  }, [lines])

  // active count = active HQ 들의 구현 agent 합 (현재 working 시각화)
  const stats = useMemo(() => {
    let active = 0
    let idle = 0
    for (const hq of HEADQUARTERS) {
      const isHqActive = activeHqs.has(hq.key)
      for (const agent of hq.agents) {
        if (!agent.implemented) continue
        if (isHqActive) active += 1
        else idle += 1
      }
    }
    return { active, idle, unimpl: UNIMPLEMENTED_AGENTS, total: TOTAL_AGENTS }
  }, [activeHqs])

  const currentNodes = useMemo(() => {
    return Array.from(new Set(Object.values(currentNodeByHq))).sort()
  }, [currentNodeByHq])

  const visibleHqs = useMemo(() => {
    if (filter === 'all') return HEADQUARTERS
    return HEADQUARTERS.filter((h) => h.key === filter)
  }, [filter])

  const handleStart = async () => {
    if (running) return
    if (!request.trim()) return
    if (!auth.loggedIn) {
      setError('Claude 로그인이 필요합니다. 우측 상단 [로그인] 버튼을 눌러주세요.')
      return
    }
    setError(null)
    setRunning(true)
    setLines([])
    setAgentMessages([])
    setActiveHqs(new Set())
    setCurrentNodeByHq({})
    setExpandedMsg(new Set())
    setResultEvent(null)
    setExeRunMessage(null)
    setCheckpoint(null)
    try {
      const path = await invoke<string>('start_run', {
        request,
        track: 'A',
        buildTarget,
        maxIterations: clampMaxIterations(maxIterStr),
        enableTechScout,
        autoIterate,
        intervene: interveneEnabled,
      })
      setEventsPath(path)
    } catch (e) {
      const msg = String(e ?? 'unknown')
      setError(msg)
      setRunning(false)
    }
  }

  const handleOpenExe = async (path: string) => {
    setExeRunMessage(null)
    try {
      // P19 — open_exe 가 타깃 인지형: web(.html) → vite preview + 브라우저, desktop(.exe) → 실행.
      await invoke<void>('open_exe', { path })
      setExeRunMessage(
        isWebArtifact(path)
          ? 'vite preview 로 로컬 서버 기동 — 잠시 후 기본 브라우저가 열립니다 (보통 localhost:4173, 점유 시 자동 포트).'
          : `실행 시작: ${path.split(/[\\/]/).pop() ?? path}`,
      )
    } catch (e) {
      setExeRunMessage(`실행 실패: ${String(e ?? 'unknown')}`)
    }
  }

  // P20 — 체크포인트 제출. action='inject'(피드백 반영) | 'continue'(그냥 계속).
  // intervention_file 절대경로(checkpoint 이벤트 제공)에 원자적 기록 → 하네스가 폴링해 읽음.
  const handleCheckpoint = async (action: 'inject' | 'continue') => {
    const file = checkpoint?.intervention_file
    setCheckpoint(null) // 패널 즉시 닫기 (하네스는 파일/타임아웃으로 진행)
    if (!file) return
    try {
      await invoke<void>('write_intervention_file', {
        path: String(file),
        feedback: action === 'inject' ? checkpointFeedback : '',
        action,
      })
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[Checkpoint] intervention 기록 실패', e)
      setError(`개입 피드백 전달 실패: ${String(e ?? 'unknown')}`)
    }
  }

  const handleLogin = async () => {
    setError(null)
    try {
      const status = await invoke<AuthStatus>('claude_auth_login')
      setAuth(status)
    } catch (e) {
      setError(`로그인 실패: ${String(e ?? 'unknown')}`)
    }
  }

  const handleLogout = async () => {
    const msg = running
      ? '⚠️ 진행 중인 작업이 있습니다.\n로그아웃 시 sidecar 의 후속 LLM 호출이 인증 만료로 실패할 수 있습니다.\n그래도 로그아웃 하시겠습니까?'
      : '로그아웃 하시겠습니까?'
    if (!window.confirm(msg)) return
    try {
      await invoke<void>('claude_auth_logout')
      setAuth(EMPTY_AUTH)
    } catch (e) {
      setError(`로그아웃 실패: ${String(e ?? 'unknown')}`)
    }
  }

  const toggleMsg = (i: number) => {
    setExpandedMsg((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  const selectedAgentMessages = selectedAgent ? agentMessages.slice(-20) : []
  const selectedHq = selectedAgent
    ? HEADQUARTERS.find((h) => h.key === selectedAgent.hq)
    : undefined

  return (
    <div className="h-screen w-screen flex flex-col bg-[#0d1117] text-slate-100">
      {/* ============ 0. P20 개입 체크포인트 패널 (modal overlay) ============ */}
      {checkpoint && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
          <div className="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-lg border-2 border-amber-500/70 bg-[#161b22] shadow-2xl">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-700">
              <div className="flex items-center gap-2">
                <span className="text-lg">🙋</span>
                <span className="text-sm font-bold text-amber-300">
                  {Number(checkpoint.iteration ?? 0) >= 2
                    ? `개입 체크포인트 — iter ${Number(checkpoint.iteration)} (직전 빌드 검토)`
                    : '개입 체크포인트 — codegen 직전'}
                </span>
              </div>
              <span
                className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${
                  checkpointRemaining <= 10
                    ? 'bg-red-600/40 text-red-200'
                    : 'bg-slate-700/60 text-slate-200'
                }`}
                title="남은 시간 — 0 이 되면 자동 진행"
              >
                ⏳ {checkpointRemaining}s
              </span>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto px-5 py-3 space-y-3">
              {/* P22 — iter 2+ 전용: 직전 iteration 빌드 검토 (web=vite preview / desktop=.exe). */}
              {Number(checkpoint.iteration ?? 0) >= 2 && (
                <div className="rounded border border-sky-700/50 bg-sky-950/30 p-2 space-y-2">
                  <div className="text-[10px] uppercase tracking-wide text-sky-300">
                    직전 iteration 빌드 — 실제 앱을 확인한 뒤 피드백 주입
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      void handleOpenExe(String(checkpoint.prev_build_path ?? ''))
                    }
                    disabled={!String(checkpoint.prev_build_path ?? '').trim()}
                    className="px-3 py-1.5 rounded bg-sky-700 hover:bg-sky-600 active:bg-sky-800 disabled:bg-slate-700 disabled:text-slate-500 text-white text-xs font-semibold"
                  >
                    ▶ 빌드 열어보기
                  </button>
                  {!String(checkpoint.prev_build_path ?? '').trim() && (
                    <div className="text-[10px] text-slate-400">
                      직전 빌드 없음/실패 — 아래 gap 요약·피드백은 그대로 가능합니다.
                    </div>
                  )}
                  {exeRunMessage && (
                    <div className="text-[10px] text-sky-300 break-words">{exeRunMessage}</div>
                  )}
                </div>
              )}
              <div>
                <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">
                  {Number(checkpoint.iteration ?? 0) >= 2
                    ? '계획 / 직전 gap·QA / 빌드 요약'
                    : '계획 / 스펙 요약'}
                </div>
                <pre className="text-[11px] text-slate-300 whitespace-pre-wrap break-words bg-slate-950/60 rounded p-2 max-h-[40vh] overflow-y-auto leading-relaxed">
                  {String(checkpoint.plan_summary ?? '(요약 없음)')}
                </pre>
              </div>
              <div>
                <label
                  htmlFor="checkpoint-feedback"
                  className="block text-[10px] uppercase tracking-wide text-slate-400 mb-1"
                >
                  피드백 (선택) — 코드 생성에 반영할 지시
                </label>
                <textarea
                  id="checkpoint-feedback"
                  rows={4}
                  value={checkpointFeedback}
                  onChange={(e) => setCheckpointFeedback(e.target.value)}
                  placeholder="예: 다크 테마로, 좌측 사이드바에 필터 추가, 모바일 반응형 우선…"
                  className="w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500 resize-none"
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-slate-700">
              <button
                type="button"
                onClick={() => void handleCheckpoint('continue')}
                className="px-3 py-1.5 rounded border border-slate-600 hover:border-slate-400 text-slate-200 text-xs"
              >
                그냥 계속
              </button>
              <button
                type="button"
                onClick={() => void handleCheckpoint('inject')}
                disabled={!checkpointFeedback.trim()}
                className="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 active:bg-amber-700 disabled:bg-slate-700 disabled:text-slate-500 text-white text-xs font-semibold"
              >
                주입 후 계속
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ============ 1. Top Toolbar ============ */}
      <header className="flex-shrink-0 border-b border-slate-800 bg-[#161b22]">
        <div className="px-6 py-2.5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-semibold text-slate-200">에이전트 오피스</span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-400">본부 {HEADQUARTERS.length}</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {authLoading ? (
              <>
                <span className="w-2 h-2 rounded-full bg-slate-500 animate-pulse" />
                <span className="text-slate-400">인증 확인 중…</span>
              </>
            ) : auth.loggedIn ? (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                <span className="text-slate-200 max-w-[14rem] truncate" title={auth.email ?? ''}>
                  {auth.email ?? '(이메일 없음)'}
                </span>
                {auth.subscriptionType?.toLowerCase() === 'max' && (
                  <span className="px-2 py-0.5 rounded bg-emerald-600/30 border border-emerald-500/60 text-emerald-200 text-xs font-bold">
                    MAX
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="ml-1 px-3 py-1 rounded-md border border-slate-600 hover:border-slate-400 text-slate-200 hover:text-white text-xs"
                >
                  로그아웃
                </button>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-red-500" />
                <span className="text-slate-300">Claude 로그인 필요</span>
                <button
                  type="button"
                  onClick={() => void handleLogin()}
                  className="ml-1 px-3 py-1 rounded-md bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold"
                >
                  로그인
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* ============ 2. Stats Bar ============ */}
      <div className="flex-shrink-0 border-b border-slate-800 bg-[#0d1117]/80 px-6 py-2 flex items-center gap-4 text-xs overflow-x-auto whitespace-nowrap">
        <div className="flex items-center gap-3">
          <span className="text-slate-400">
            ACTIVE <span className="text-emerald-400 font-bold text-sm">{stats.active}</span>
          </span>
          <span className="text-slate-400">
            IDLE <span className="text-slate-200 font-bold text-sm">{stats.idle}</span>
          </span>
          <span className="text-slate-400">
            미구현 <span className="text-slate-500 font-bold text-sm">{stats.unimpl}</span>
          </span>
          <span className="text-slate-400">
            전체 <span className="text-slate-100 font-bold text-sm">{stats.total}</span>
          </span>
        </div>
        <span className="text-slate-700">|</span>
        {currentNodes.length > 0 ? (
          <span className="text-slate-300">
            실행 중:{' '}
            {currentNodes.map((n) => (
              <code
                key={n}
                className="mx-1 px-1.5 py-0.5 bg-emerald-900/40 text-emerald-300 rounded font-mono"
              >
                {n}
              </code>
            ))}
          </span>
        ) : (
          <span className="text-slate-500">idle</span>
        )}
        <span className="ml-auto flex items-center gap-2 text-slate-400">
          <span>Telemetry:</span>
          <span className="text-blue-300">status {counts.agent_status}</span>
          <span className="text-purple-300">msg {counts.agent_message}</span>
          <span className="text-emerald-300">iter {counts.iteration_progress}</span>
          <span className="text-amber-300">result {counts.result}</span>
          <span className="text-slate-300">meta {counts.tail_meta}</span>
        </span>
      </div>

      {/* ============ 2.5. Result Banner (exe_path 있을 때만) ============ */}
      {resultEvent && (
        <div
          className={`flex-shrink-0 border-b border-slate-800 px-6 py-2.5 flex items-center gap-3 text-xs ${
            resultEvent.verdict === 'COMPLETE' || resultEvent.exe_path
              ? 'bg-emerald-950/40 border-emerald-800'
              : 'bg-amber-950/40 border-amber-800'
          }`}
        >
          {resultEvent.exe_path ? (
            <>
              <span className="text-lg">✅</span>
              <div className="flex-1 min-w-0">
                <div className="text-emerald-300 font-semibold">
                  {isWebArtifact(String(resultEvent.exe_path))
                    ? `web 빌드 완료 — verdict: ${String(resultEvent.verdict ?? '')}`
                    : `실행 파일 생성 완료 — verdict: ${String(resultEvent.verdict ?? '')}`}
                </div>
                <div
                  className="text-slate-400 text-[10px] mt-0.5 truncate font-mono"
                  title={String(resultEvent.exe_path)}
                >
                  {String(resultEvent.exe_path)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => void handleOpenExe(String(resultEvent.exe_path))}
                title={
                  isWebArtifact(String(resultEvent.exe_path))
                    ? 'vite preview 로 dist 서빙 후 기본 브라우저로 열기 (보통 localhost:4173)'
                    : '빌드된 .exe 실행'
                }
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white rounded text-xs font-semibold whitespace-nowrap"
              >
                {isWebArtifact(String(resultEvent.exe_path)) ? '▶ 브라우저로 열기' : '▶ 실행'}
              </button>
              <button
                type="button"
                onClick={() => setResultEvent(null)}
                className="px-2 py-1 text-slate-400 hover:text-slate-200 text-lg leading-none"
                title="배너 닫기"
              >
                ×
              </button>
            </>
          ) : (
            <>
              <span className="text-lg">⚠</span>
              <div className="flex-1 min-w-0">
                <div className="text-amber-300 font-semibold">
                  실행 종료 — verdict: {String(resultEvent.verdict ?? '')}
                </div>
                <div className="text-slate-400 text-[10px] mt-0.5">
                  {String(resultEvent.summary_line ?? resultEvent.blocked_cause ?? '산출물 경로 없음 (빌드 타깃 "빌드 없음" 또는 빌드 단계 실패)')}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setResultEvent(null)}
                className="px-2 py-1 text-slate-400 hover:text-slate-200 text-lg leading-none"
                title="배너 닫기"
              >
                ×
              </button>
            </>
          )}
        </div>
      )}
      {exeRunMessage && (
        <div className="flex-shrink-0 border-b border-slate-800 bg-slate-900 px-6 py-1.5 text-[10px] text-slate-300 flex items-center justify-between">
          <span>{exeRunMessage}</span>
          <button
            type="button"
            onClick={() => setExeRunMessage(null)}
            className="text-slate-500 hover:text-slate-200"
            title="닫기"
          >
            ×
          </button>
        </div>
      )}

      {/* ============ 3. Filter Bar ============ */}
      <div className="flex-shrink-0 border-b border-slate-800 bg-[#161b22] px-6 py-2 flex items-center gap-1.5 overflow-x-auto whitespace-nowrap">
        <button
          type="button"
          onClick={() => setFilter('all')}
          className={`px-2.5 py-1 rounded text-xs font-semibold transition ${
            filter === 'all'
              ? 'bg-sky-600 text-white'
              : 'bg-slate-800/50 text-slate-300 hover:bg-slate-700/60'
          }`}
        >
          전체
        </button>
        {HEADQUARTERS.map((hq) => (
          <button
            key={hq.key}
            type="button"
            onClick={() => setFilter(hq.key)}
            className={`px-2.5 py-1 rounded text-xs transition border ${
              filter === hq.key
                ? `${hq.borderClass.replace('/60', '')} ${hq.bgClass.replace('/25', '/50').replace('/20', '/50').replace('/30', '/50')} ${hq.accentClass} font-semibold`
                : 'border-transparent bg-slate-800/40 text-slate-300 hover:bg-slate-700/60'
            }`}
          >
            본부 {hq.no} · {hq.filterLabel}
          </button>
        ))}
      </div>

      {/* ============ Main 3-pane ============ */}
      <div className="flex-1 flex min-h-0">
        {/* === Sidebar === */}
        <aside className="w-[150px] flex-shrink-0 border-r border-slate-800 bg-[#161b22] flex flex-col">
          <div className="px-4 pt-4 pb-3 border-b border-slate-800">
            <div className="text-sm font-bold text-sky-400 leading-tight">Nexus Alpha</div>
            <div className="text-[10px] text-slate-500 leading-tight mt-0.5">
              Agent Office v13 — Boardroom
            </div>
          </div>
          <nav className="flex-1 overflow-y-auto py-2">
            {MENU_ITEMS.map((m) => {
              const isActive = activeMenu === m.key
              return (
                <button
                  key={m.key}
                  type="button"
                  onClick={() => m.enabled && setActiveMenu(m.key)}
                  disabled={!m.enabled}
                  className={`w-full text-left px-3 py-2 text-xs border-l-2 transition ${
                    isActive
                      ? 'border-sky-500 bg-sky-500/10 text-sky-300'
                      : m.enabled
                        ? 'border-transparent text-slate-300 hover:bg-slate-800/50 hover:border-slate-600'
                        : 'border-transparent text-slate-600 cursor-not-allowed'
                  }`}
                  title={m.enabled ? undefined : '준비 중'}
                >
                  {m.label}
                </button>
              )
            })}
          </nav>
          {/* PR #228 — 부서 대표 (이사회 참석자) 범례. agent-map 메뉴 활성 시만. */}
          {activeMenu === 'agent-map' && (
            <div className="flex-shrink-0 border-t border-slate-800 px-3 py-2">
              <div className="text-[9px] text-slate-500 uppercase tracking-wide mb-1">
                범례
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-slate-300">
                <span className="text-[14px] leading-none">👑</span>
                <span>부서 대표 (이사회 참석)</span>
              </div>
              <div
                className="mt-1 inline-flex items-center gap-1.5 text-[10px] text-slate-400 px-1.5 py-0.5 rounded border-2"
                style={{ borderColor: '#f5c842', backgroundColor: 'rgba(245,200,66,0.10)' }}
              >
                <span>금색 테두리</span>
              </div>
            </div>
          )}
          <div className="flex-shrink-0 border-t border-slate-800 p-3 space-y-2">
            <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
              자연어 요청
            </label>
            <textarea
              rows={3}
              className="w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 resize-none"
              placeholder="예: 칸반 보드 앱"
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              disabled={running}
            />
            {/* P18 — 빌드 타깃 선택 (web 기본 / desktop / 빌드 없음) */}
            <div className="space-y-1">
              <label
                htmlFor="build-target"
                className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wide"
              >
                빌드 타깃
              </label>
              <select
                id="build-target"
                value={buildTarget}
                onChange={(e) => setBuildTarget(e.target.value as BuildTarget)}
                disabled={running}
                title="web = vite → dist/index.html (기본) · desktop = PyInstaller .exe · none = 빌드 없음(사양만)"
                className="w-full px-1.5 py-1 bg-slate-900 border border-slate-700 rounded text-[10px] text-slate-100 focus:outline-none focus:border-sky-500 disabled:text-slate-500"
              >
                <option value="web">web (vite → dist)</option>
                <option value="desktop">desktop (.exe)</option>
                <option value="none">빌드 없음</option>
              </select>
            </div>

            {/* P18 — auto-iterate (자기 진화 루프) + max-iterations (1~10) */}
            <label
              className="flex items-center gap-1.5 text-[10px] text-slate-300 cursor-pointer select-none"
              title="Convergence Judge 가 COMPLETE/BLOCKED 판정까지 최대 max-iter 회 반복(자기 진화). 비용 주의 — iter 당 ~25min."
            >
              <input
                type="checkbox"
                checked={autoIterate}
                onChange={(e) => setAutoIterate(e.target.checked)}
                disabled={running}
                className="accent-sky-500"
              />
              <span>auto-iterate (자기 진화)</span>
            </label>
            <div
              className="flex items-center justify-between gap-2"
              title={
                autoIterate
                  ? 'auto-iterate 시 최대 반복 횟수 (1~10). COMPLETE/BLOCKED 판정 시 조기 종료.'
                  : 'auto-iterate 가 OFF 라 비활성 (1회 실행). auto-iterate 를 켜면 적용됩니다.'
              }
            >
              <label
                htmlFor="max-iter"
                className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide"
              >
                max-iter
              </label>
              <input
                id="max-iter"
                type="number"
                min={1}
                max={10}
                value={maxIterStr}
                onChange={(e) => setMaxIterStr(e.target.value)}
                onBlur={() => setMaxIterStr(String(clampMaxIterations(maxIterStr)))}
                disabled={running || !autoIterate}
                className="w-14 px-1.5 py-1 bg-slate-900 border border-slate-700 rounded text-[10px] text-slate-100 text-right focus:outline-none focus:border-sky-500 disabled:text-slate-500"
              />
            </div>

            {/* P18 — tech-scout (PyPI 가짜 패키지 가드) 토글 */}
            <label
              className="flex items-center gap-1.5 text-[10px] text-slate-300 cursor-pointer select-none"
              title="PyPI 가짜 패키지(환각) 가드 — Engineer 산출 requirements 의 각 패키지 실존을 PyPI API 로 검증."
            >
              <input
                type="checkbox"
                checked={enableTechScout}
                onChange={(e) => setEnableTechScout(e.target.checked)}
                disabled={running}
                className="accent-sky-500"
              />
              <span>tech-scout (패키지 가드)</span>
            </label>

            {/* P20 — 런 중 사람 개입 체크포인트 토글 (기본 OFF) */}
            <label
              className="flex items-center gap-1.5 text-[10px] text-slate-300 cursor-pointer select-none"
              title="codegen 직전 1회 멈춰 계획/스펙을 보여주고 피드백을 받습니다. 무입력 시 타임아웃 자동 진행. OFF(기본)면 멈춤 없음."
            >
              <input
                type="checkbox"
                checked={interveneEnabled}
                onChange={(e) => setInterveneEnabled(e.target.checked)}
                disabled={running}
                className="accent-sky-500"
              />
              <span>런 중 개입 (codegen 직전)</span>
            </label>
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={running || !request.trim()}
              className="w-full px-2 py-1.5 bg-sky-600 hover:bg-sky-500 active:bg-sky-700 disabled:bg-slate-700 disabled:text-slate-500 rounded text-xs font-semibold"
            >
              {running ? '실행 중…' : '시작'}
            </button>
            {error && <p className="text-[10px] text-red-400 break-words">{error}</p>}
            {eventsPath && (
              <p className="text-[9px] text-slate-500 break-all" title={eventsPath}>
                …{eventsPath.slice(-26)}
              </p>
            )}
          </div>
        </aside>

        {/* === Center Office === */}
        <main className="flex-1 min-w-0 overflow-hidden bg-[#0d1117] flex flex-col">
          {activeMenu === 'boardroom' ? (
            <div className="flex-1 min-h-0">
              <BoardroomPanel />
            </div>
          ) : activeMenu === 'run-report' ? (
            <div className="flex-1 min-h-0">
              <RunReportPanel />
            </div>
          ) : activeMenu !== 'agent-map' ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm">
              "{MENU_ITEMS.find((m) => m.key === activeMenu)?.label}" 메뉴는 준비 중입니다.
            </div>
          ) : (
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
            <div
              className={`grid gap-3 ${
                filter === 'all'
                  ? 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3'
                  : 'grid-cols-1'
              }`}
            >
              {visibleHqs.map((hq) => {
                const isActive = activeHqs.has(hq.key)
                const currentNode = currentNodeByHq[hq.key]
                const implCount = hq.agents.filter((a) => a.implemented).length
                return (
                  <section
                    key={hq.key}
                    className={`relative border-2 ${hq.borderClass} ${hq.bgClass} rounded-lg p-2.5`}
                  >
                    {isActive && (
                      <div
                        className="absolute inset-0 rounded-lg pointer-events-none animate-dept-pulse"
                        style={{ '--pulse-color': hq.pulseRgba } as React.CSSProperties}
                      />
                    )}
                    <header className="flex items-center justify-between mb-2 relative">
                      <h2 className={`text-[11px] font-bold tracking-wide ${hq.accentClass}`}>
                        본부 {hq.no} · {hq.label}
                      </h2>
                      <span className="text-[9px] text-slate-400 font-mono">
                        {isActive && currentNode ? currentNode : `${implCount}/${hq.agents.length}`}
                      </span>
                    </header>
                    <div
                      className={`grid gap-1.5 relative ${
                        filter === 'all' ? 'grid-cols-3' : 'grid-cols-4 md:grid-cols-6'
                      }`}
                    >
                      {hq.agents.map((agent) => {
                        const isSelected = selectedAgent?.name === agent.name
                        const isAgentActive = agent.implemented && isActive
                        // PR #228 — 부서 대표 (이사회 참석자) 표시. 미구현 시 X.
                        const isRep = Boolean(
                          agent.implemented && agent.is_representative,
                        )
                        const model = effectiveModel(agent, hq)
                        const tools = effectiveTools(agent, hq)
                        const pipelines = effectivePipelines(agent, hq)
                        // 외곽 className 결정 — Active(emerald 펄스) 우선,
                        // 비-Active 면 isRep(금색 #f5c842 2px) > 기본(투명)
                        const outlineClass = isAgentActive
                          ? 'animate-card-pulse border-emerald-400'
                          : isRep
                            ? 'border-2 border-[#f5c842] bg-[#f5c842]/10'
                            : 'border-transparent hover:bg-slate-800/40'
                        return (
                          <button
                            key={agent.name}
                            type="button"
                            onClick={() => setSelectedAgent(agent)}
                            className={`relative flex flex-col items-center gap-0.5 p-1.5 rounded transition border ${outlineClass} ${
                              isSelected ? 'ring-1 ring-sky-400 bg-slate-800/40' : ''
                            } ${!agent.implemented ? 'opacity-70' : ''}`}
                            title={[
                              agent.name,
                              `모델: ${model}`,
                              !agent.implemented
                                ? '상태: 미구현'
                                : isAgentActive
                                  ? `상태: WORKING — ${currentNode ?? ''}`
                                  : '상태: IDLE',
                              isRep ? '👑 부서 대표 (이사회 참석)' : null,
                              `도구 ${tools.length}개`,
                              `파이프라인: ${pipelines.join(', ')}`,
                            ]
                              .filter(Boolean)
                              .join('\n')}
                          >
                            {isRep && (
                              <span
                                className="absolute -top-1 -right-1 text-[12px] z-10 leading-none drop-shadow"
                                aria-label="부서 대표 (이사회 참석)"
                              >
                                👑
                              </span>
                            )}
                            <PixelCharacter
                              bgClass={hq.charBgClass}
                              bobbing={isAgentActive}
                              faded={!agent.implemented}
                            />
                            <span className="text-[8px] text-slate-200 leading-tight text-center line-clamp-2 break-words w-full">
                              {agent.name}
                            </span>
                            {!agent.implemented ? (
                              <span className="text-[8px] px-1 rounded bg-slate-700/60 text-slate-400 border border-slate-600 flex items-center gap-0.5">
                                <span>🔒</span>
                                <span>미구현</span>
                              </span>
                            ) : isAgentActive ? (
                              <span className="text-[8px] px-1.5 py-0.5 rounded bg-emerald-500 text-slate-900 font-bold tracking-wide shadow shadow-emerald-500/40">
                                ACTIVE
                              </span>
                            ) : (
                              <span className="text-[7px] px-1 rounded bg-slate-700/40 text-slate-400">
                                idle
                              </span>
                            )}
                          </button>
                        )
                      })}
                    </div>
                  </section>
                )
              })}
            </div>
            </div>
          )}
        </main>

        {/* === Right Detail Panel (280px) === */}
        <aside className="w-[280px] flex-shrink-0 border-l border-slate-800 bg-[#161b22] overflow-y-auto">
          {!selectedAgent || !selectedHq ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-xs px-4 text-center">
              에이전트를 클릭하세요
            </div>
          ) : (
            <div className="p-4 space-y-3">
              {/* Header */}
              <div>
                <h3 className="text-base font-bold text-slate-100 leading-tight break-words">
                  {selectedAgent.name}
                </h3>
                <p className={`text-[10px] uppercase tracking-wide mt-1 ${selectedHq.accentClass}`}>
                  본부 {selectedHq.no} · {selectedHq.label}
                </p>
                <div className="flex items-center gap-2 mt-2 text-[10px]">
                  <span className="text-slate-500">Model:</span>
                  <code className="px-1.5 py-0.5 bg-slate-800 rounded text-slate-200 font-mono">
                    {effectiveModel(selectedAgent, selectedHq)}
                  </code>
                </div>
              </div>

              {/* Status */}
              <div className="flex items-center gap-2 flex-wrap">
                {!selectedAgent.implemented ? (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-slate-700/60 text-slate-300 border border-slate-600 flex items-center gap-1">
                    🔒 미구현
                  </span>
                ) : (
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                      activeHqs.has(selectedAgent.hq)
                        ? 'bg-emerald-500 text-slate-900'
                        : 'bg-slate-700/40 text-slate-400'
                    }`}
                  >
                    {activeHqs.has(selectedAgent.hq) ? 'ACTIVE' : 'IDLE'}
                  </span>
                )}
                {currentNodeByHq[selectedAgent.hq] && (
                  <span className="text-[10px] text-slate-400 font-mono truncate">
                    {currentNodeByHq[selectedAgent.hq]}
                  </span>
                )}
              </div>

              {/* Role */}
              <div>
                <h4 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">
                  역할
                </h4>
                <p className="text-xs text-slate-300 leading-snug">{selectedAgent.role}</p>
                {selectedAgent.goalDetailed && (
                  <p className="text-[11px] text-slate-400 leading-relaxed mt-1.5 whitespace-pre-wrap">
                    {selectedAgent.goalDetailed}
                  </p>
                )}
              </div>

              {/* Tools */}
              <div>
                <h4 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                  사용 도구 ({effectiveTools(selectedAgent, selectedHq).length})
                </h4>
                <div className="flex flex-wrap gap-1">
                  {effectiveTools(selectedAgent, selectedHq).map((tool) => (
                    <span
                      key={tool}
                      className="text-[10px] px-1.5 py-0.5 bg-slate-800 rounded text-slate-300 border border-slate-700 font-mono"
                    >
                      {tool}
                    </span>
                  ))}
                </div>
              </div>

              {/* Pipelines */}
              <div>
                <h4 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                  파이프라인
                </h4>
                <div className="flex flex-wrap gap-1">
                  {effectivePipelines(selectedAgent, selectedHq).map((p) => (
                    <span
                      key={p}
                      className="text-[10px] px-1.5 py-0.5 bg-sky-900/40 rounded text-sky-300 border border-sky-700/60"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </div>

              {/* Chat history */}
              <div>
                <h4 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                  실시간 대화 내역 ({selectedAgentMessages.length})
                </h4>
                <div className="space-y-1.5 max-h-[35vh] overflow-y-auto">
                  {selectedAgentMessages.length === 0 ? (
                    <p className="text-[10px] text-slate-500 italic">
                      {selectedAgent.implemented
                        ? '(LLM 호출 발생 시 표시됩니다)'
                        : '(미구현 에이전트 — 대화 없음)'}
                    </p>
                  ) : (
                    selectedAgentMessages.map((m, i) => {
                      const isExpanded = expandedMsg.has(i)
                      const fullText = String(
                        m.output_preview ?? m.prompt_preview ?? '(empty)',
                      )
                      const sender = String(m.agent ?? m.department ?? 'unknown')
                      return (
                        <button
                          key={i}
                          type="button"
                          onClick={() => toggleMsg(i)}
                          className="w-full text-left border border-slate-800 rounded p-2 bg-slate-900/40 hover:bg-slate-900/60 transition"
                        >
                          <div className="flex items-center justify-between text-[9px] text-slate-500 mb-1">
                            <span className="font-mono truncate max-w-[60%]" title={sender}>
                              {sender}
                            </span>
                            <span>{m.ts?.slice(11, 19) ?? ''}</span>
                          </div>
                          <p
                            className={`text-[11px] text-slate-300 break-words ${
                              isExpanded ? 'whitespace-pre-wrap' : 'line-clamp-2'
                            }`}
                          >
                            {fullText}
                          </p>
                          <div className="text-[9px] text-slate-500 mt-1 text-right">
                            {isExpanded ? '클릭하여 접기' : '클릭하여 펼치기'}
                          </div>
                        </button>
                      )
                    })
                  )}
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>

      {/* ============ Bottom Telemetry stream ============ */}
      <section className="flex-shrink-0 border-t border-slate-800 bg-[#161b22] p-2 max-h-[140px] flex flex-col">
        <div className="flex flex-wrap items-center gap-2 text-[10px] mb-1 px-1">
          <span className="font-semibold text-slate-200">Stream</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-400">
            <span className="text-slate-100 font-semibold">{lines.length}</span> line
          </span>
        </div>
        <pre className="flex-1 overflow-auto text-[10px] font-mono text-slate-300 bg-slate-950/60 rounded p-2 leading-tight">
          {lines.length === 0
            ? running
              ? '// Python sidecar 시작됨 — 첫 event 대기 중…'
              : '// (시작 버튼을 누르면 events.jsonl 이 tail 됩니다)'
            : lines
                .map((l) => {
                  if (!l.parsed) return `[raw] ${l.raw}`
                  if (l.parsed.type === 'tail_meta') {
                    return `[tail_meta] ${l.parsed.kind ?? '?'} — ${l.parsed.detail ?? l.parsed.path ?? ''}`
                  }
                  const main = l.parsed.agent ?? l.parsed.phase ?? l.parsed.verdict ?? ''
                  const status = l.parsed.status ?? ''
                  return `[${l.parsed.type ?? '?'}] ${main}  ${status}`.trim()
                })
                .join('\n')}
        </pre>
      </section>
    </div>
  )
}

export default App
