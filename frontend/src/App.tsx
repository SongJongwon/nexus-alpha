import { useCallback, useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

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
      },
      {
        name: 'CEO',
        role: 'Chief Executive Officer (Phase 8 예정)',
        goalDetailed:
          '다중 프로젝트 동시 진행 시 의미. 단일 프로젝트 사이클은 CTO + Convergence Judge 로 충분.',
        implemented: false,
        hq: 'hq-0',
      },
      {
        name: 'CFO',
        role: 'Chief Financial Officer (Phase 8 예정)',
        goalDetailed: '비용 / 토큰 / API 한도 관리. 현재는 BUDGET 게이트가 결정론으로 처리.',
        implemented: false,
        hq: 'hq-0',
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
        name: 'Business Process Analyst',
        role: '업무 프로세스 분석 (미구현)',
        goalDetailed: 'BPMN/swim lane 등 업무 흐름 모델링. 현재 미구현.',
        implemented: false,
        hq: 'hq-1',
      },
      {
        name: 'Use Case Specialist',
        role: '유스케이스 명세 (미구현)',
        goalDetailed: 'Use case diagram + scenario script 작성. 현재 미구현.',
        implemented: false,
        hq: 'hq-1',
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
      },
      {
        name: 'Product Manager',
        role: '제품 전략 (미구현)',
        implemented: false,
        hq: 'hq-2',
      },
      {
        name: 'Project Coordinator',
        role: '프로젝트 coordination (미구현)',
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
        implemented: false,
        hq: 'hq-9',
      },
      {
        name: 'UI Automation Specialist',
        role: 'PyAutoGUI/Playwright (Phase B)',
        implemented: false,
        hq: 'hq-9',
      },
      {
        name: 'Runtime Failure Analyzer',
        role: '실행 fail trace 분석 (Phase C)',
        implemented: false,
        hq: 'hq-9',
      },
      {
        name: 'Auto-Fix Coordinator',
        role: 'RV 재빌드 trigger (Phase C)',
        implemented: false,
        hq: 'hq-9',
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
        name: 'Meeting Facilitator',
        role: '킥오프 회의 + shared assumptions',
        goalDetailed:
          'kickoff_meeting 노드. 모든 부서가 *공유 가정* (real-time vs cached 등) 을 합의. 환율 변환기 사례 같은 cross-agent inconsistency 차단.',
        implemented: true,
        hq: 'hq-10',
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
        role: '본부 5 → 본부 10 조직개편 (미구현, Phase 3)',
        implemented: false,
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

type MenuKey = 'agent-map' | 'system' | 'monitor' | 'catalog' | 'usage' | 'settings'

interface MenuItem {
  key: MenuKey
  label: string
  enabled: boolean
}

const MENU_ITEMS: MenuItem[] = [
  { key: 'agent-map', label: '에이전트 맵', enabled: true },
  { key: 'system', label: '시스템 개요', enabled: false },
  { key: 'monitor', label: '실시간 모니터', enabled: false },
  { key: 'catalog', label: '카탈로그', enabled: false },
  { key: 'usage', label: '사용 통계', enabled: false },
  { key: 'settings', label: '설정', enabled: false },
]

type FilterKey = 'all' | HQKey

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

      if (
        parsed?.type === 'result' ||
        (parsed?.type === 'iteration_progress' && parsed.phase === 'run_end')
      ) {
        setRunning(false)
        setActiveHqs(new Set())
        setCurrentNodeByHq({})
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
    try {
      const path = await invoke<string>('start_run', {
        request,
        track: 'A',
        build: false,
        maxIterations: 1,
      })
      setEventsPath(path)
    } catch (e) {
      const msg = String(e ?? 'unknown')
      setError(msg)
      setRunning(false)
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
              Agent Office v12
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
        <main className="flex-1 min-w-0 overflow-y-auto p-3 bg-[#0d1117]">
          {activeMenu !== 'agent-map' ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm">
              "{MENU_ITEMS.find((m) => m.key === activeMenu)?.label}" 메뉴는 준비 중입니다.
            </div>
          ) : (
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
                        const model = effectiveModel(agent, hq)
                        const tools = effectiveTools(agent, hq)
                        const pipelines = effectivePipelines(agent, hq)
                        return (
                          <button
                            key={agent.name}
                            type="button"
                            onClick={() => setSelectedAgent(agent)}
                            className={`relative flex flex-col items-center gap-0.5 p-1.5 rounded transition border ${
                              isAgentActive
                                ? 'animate-card-pulse border-emerald-400'
                                : 'border-transparent hover:bg-slate-800/40'
                            } ${isSelected ? 'ring-1 ring-sky-400 bg-slate-800/40' : ''} ${
                              !agent.implemented ? 'opacity-70' : ''
                            }`}
                            title={[
                              agent.name,
                              `모델: ${model}`,
                              !agent.implemented
                                ? '상태: 미구현'
                                : isAgentActive
                                  ? `상태: WORKING — ${currentNode ?? ''}`
                                  : '상태: IDLE',
                              `도구 ${tools.length}개`,
                              `파이프라인: ${pipelines.join(', ')}`,
                            ].join('\n')}
                          >
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
