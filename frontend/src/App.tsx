import { useCallback, useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

// =============================================================================
// Sprint 6 — Agent Office (조직도 v12 기준 11 본부 + 54 멤버 전체 시각화)
// =============================================================================
//
// 본 file 은 docs/architecture/Nexus_Alpha_조직도_v12.md 의 11 본부 + 54 멤버
// 정의를 그대로 반영. 구현 39 명은 부서별 색상 character, 미구현 15 명은 회색
// + "미구현" 뱃지. Telemetry 노드 → 본부 다중 매핑 (run_chain → 본부 0+3+4).
//
// 백엔드 코드 변경 0 — 본 변경은 frontend 의 *시각화 layer* 만.

// =============================================================================
// 1. 타입 + 본부 11 + 멤버 54 정의 (조직도 v12)
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

interface AgentInfo {
  name: string
  role: string
  implemented: boolean
  hq: HQKey
}

interface HeadquartersDef {
  key: HQKey
  no: number
  label: string
  borderClass: string
  bgClass: string
  accentClass: string
  charBgClass: string // 구현된 agent character 색상
  pulseRgba: string
  agents: AgentInfo[]
}

const HEADQUARTERS: HeadquartersDef[] = [
  {
    key: 'hq-0',
    no: 0,
    label: 'C-Level',
    borderClass: 'border-amber-500/60',
    bgClass: 'bg-amber-950/20',
    accentClass: 'text-amber-300',
    charBgClass: 'bg-amber-300',
    pulseRgba: 'rgba(245, 158, 11, 0.5)',
    agents: [
      { name: 'CTO', role: 'Chief Technology Officer — 기술 전략', implemented: true, hq: 'hq-0' },
      { name: 'CEO', role: 'Chief Executive Officer (Phase 8 예정)', implemented: false, hq: 'hq-0' },
      { name: 'CFO', role: 'Chief Financial Officer (Phase 8 예정)', implemented: false, hq: 'hq-0' },
    ],
  },
  {
    key: 'hq-1',
    no: 1,
    label: '업무 분석',
    borderClass: 'border-sky-500/60',
    bgClass: 'bg-sky-950/25',
    accentClass: 'text-sky-300',
    charBgClass: 'bg-sky-300',
    pulseRgba: 'rgba(14, 165, 233, 0.5)',
    agents: [
      { name: 'Requirement Expander', role: '사용자 요청 YAML 확장', implemented: true, hq: 'hq-1' },
      { name: 'Gap Analyst', role: 'iteration feedback gap 분석', implemented: true, hq: 'hq-1' },
      { name: 'Data Analyst', role: 'Track B 분석 + instruction', implemented: true, hq: 'hq-1' },
      { name: 'Business Process Analyst', role: '업무 프로세스 분석 (미구현)', implemented: false, hq: 'hq-1' },
      { name: 'Use Case Specialist', role: '유스케이스 명세 (미구현)', implemented: false, hq: 'hq-1' },
    ],
  },
  {
    key: 'hq-2',
    no: 2,
    label: '기획 및 설계',
    borderClass: 'border-violet-500/60',
    bgClass: 'bg-violet-950/25',
    accentClass: 'text-violet-300',
    charBgClass: 'bg-violet-300',
    pulseRgba: 'rgba(139, 92, 246, 0.5)',
    agents: [
      { name: 'UI/UX Analyst', role: 'UI/UX 명세 + 권장 framework', implemented: true, hq: 'hq-2' },
      { name: 'Product Manager', role: '제품 전략 (미구현)', implemented: false, hq: 'hq-2' },
      { name: 'Project Coordinator', role: '프로젝트 coordination (미구현)', implemented: false, hq: 'hq-2' },
    ],
  },
  {
    key: 'hq-3',
    no: 3,
    label: '개발 (Track A + B)',
    borderClass: 'border-emerald-500/60',
    bgClass: 'bg-emerald-950/25',
    accentClass: 'text-emerald-300',
    charBgClass: 'bg-emerald-300',
    pulseRgba: 'rgba(16, 185, 129, 0.5)',
    agents: [
      { name: 'Python Engineer', role: 'Senior Python — Track A 핵심', implemented: true, hq: 'hq-3' },
      { name: 'Web Scraping Specialist', role: 'Playwright/Selenium (Track B)', implemented: true, hq: 'hq-3' },
      { name: 'API Integration Developer', role: 'REST/GraphQL (Track B)', implemented: true, hq: 'hq-3' },
      { name: 'Data Parser Engineer', role: 'Excel/PDF/CSV (Track B)', implemented: true, hq: 'hq-3' },
      { name: 'Desktop Automation Specialist', role: 'PyAutoGUI/PyWinAuto (Track B)', implemented: true, hq: 'hq-3' },
      { name: 'DevOps Engineer', role: 'Docker/CI/CD (Track B)', implemented: true, hq: 'hq-3' },
      { name: 'Mobile Developer', role: '모바일 (미구현, Phase 9)', implemented: false, hq: 'hq-3' },
      { name: 'Embedded Specialist', role: '임베디드 (미구현, Phase 9)', implemented: false, hq: 'hq-3' },
    ],
  },
  {
    key: 'hq-4',
    no: 4,
    label: '품질 검증',
    borderClass: 'border-red-500/60',
    bgClass: 'bg-red-950/25',
    accentClass: 'text-red-300',
    charBgClass: 'bg-red-300',
    pulseRgba: 'rgba(239, 68, 68, 0.5)',
    agents: [
      { name: 'Code Reviewer', role: 'Senior Code Reviewer (Static QA)', implemented: true, hq: 'hq-4' },
      { name: 'Pytest Author', role: 'Test 생성 + 검증', implemented: true, hq: 'hq-4' },
      { name: 'Code QA', role: 'pytest + ruff 실행', implemented: true, hq: 'hq-4' },
      { name: 'Functional Test Agent', role: 'Functional 테스트 suite', implemented: true, hq: 'hq-4' },
      { name: 'GUI Test Agent', role: 'pyautogui + Vision QA', implemented: true, hq: 'hq-4' },
      { name: 'Performance Engineer', role: 'Performance / profiling', implemented: true, hq: 'hq-4' },
      { name: 'Security Auditor', role: '취약점 스캔', implemented: true, hq: 'hq-4' },
      { name: 'Compliance Officer', role: '규정 검증', implemented: true, hq: 'hq-4' },
      { name: 'Robustness Tester', role: 'Chaos / edge case', implemented: true, hq: 'hq-4' },
      { name: 'Convergence Judge', role: '결정론 verdict (c_level 디렉터리, 논리적 QA)', implemented: true, hq: 'hq-4' },
    ],
  },
  {
    key: 'hq-5',
    no: 5,
    label: '지식 관리',
    borderClass: 'border-teal-500/60',
    bgClass: 'bg-teal-950/25',
    accentClass: 'text-teal-300',
    charBgClass: 'bg-teal-300',
    pulseRgba: 'rgba(20, 184, 166, 0.5)',
    agents: [
      { name: 'Knowledge Curator', role: 'YAML 인덱싱', implemented: true, hq: 'hq-5' },
      { name: 'RAG Searcher', role: '과거 workflow recall', implemented: true, hq: 'hq-5' },
      { name: 'Documentation Lead', role: '문서 관리 (미구현)', implemented: false, hq: 'hq-5' },
    ],
  },
  {
    key: 'hq-6',
    no: 6,
    label: '운영 지원',
    borderClass: 'border-slate-500/60',
    bgClass: 'bg-slate-800/30',
    accentClass: 'text-slate-300',
    charBgClass: 'bg-slate-300',
    pulseRgba: 'rgba(148, 163, 184, 0.5)',
    agents: [
      { name: 'Sandbox Runner', role: '격리 subprocess 실행', implemented: true, hq: 'hq-6' },
      { name: 'Monitoring Engineer', role: '모니터링 (미구현)', implemented: false, hq: 'hq-6' },
    ],
  },
  {
    key: 'hq-7',
    no: 7,
    label: '디자인',
    borderClass: 'border-pink-500/60',
    bgClass: 'bg-pink-950/25',
    accentClass: 'text-pink-300',
    charBgClass: 'bg-pink-300',
    pulseRgba: 'rgba(236, 72, 153, 0.5)',
    agents: [
      { name: 'GUI Code Generator', role: 'Tkinter/Flet/PyQt6 코드', implemented: true, hq: 'hq-7' },
      { name: 'GUI Designer', role: '와이어프레임 + widget tree', implemented: true, hq: 'hq-7' },
      { name: 'Theme Designer', role: 'Design tokens', implemented: true, hq: 'hq-7' },
    ],
  },
  {
    key: 'hq-8',
    no: 8,
    label: '빌드 & 배포',
    borderClass: 'border-lime-500/60',
    bgClass: 'bg-lime-950/25',
    accentClass: 'text-lime-300',
    charBgClass: 'bg-lime-300',
    pulseRgba: 'rgba(132, 204, 22, 0.5)',
    agents: [
      { name: 'Build Engineer', role: 'PyInstaller .exe', implemented: true, hq: 'hq-8' },
      { name: 'Asset Manager', role: 'Binary packaging', implemented: true, hq: 'hq-8' },
      { name: 'Changelog Generator', role: 'Release notes', implemented: true, hq: 'hq-8' },
      { name: 'Dependency Analyzer', role: 'Dep security scan', implemented: true, hq: 'hq-8' },
      { name: 'Distribution Agent', role: 'Distribution 전략', implemented: true, hq: 'hq-8' },
      { name: 'Installer Creator', role: 'NSIS Windows installer', implemented: true, hq: 'hq-8' },
      { name: 'Platform Tester', role: 'Multi-platform 테스트', implemented: true, hq: 'hq-8' },
      { name: 'Release Manager', role: 'GitHub release', implemented: true, hq: 'hq-8' },
      { name: 'Update Checker', role: 'Version 관리', implemented: true, hq: 'hq-8' },
    ],
  },
  {
    key: 'hq-9',
    no: 9,
    label: 'Runtime Verification',
    borderClass: 'border-orange-500/60',
    bgClass: 'bg-orange-950/25',
    accentClass: 'text-orange-300',
    charBgClass: 'bg-orange-300',
    pulseRgba: 'rgba(249, 115, 22, 0.5)',
    agents: [
      { name: 'Exe Runtime Tester', role: '.exe sandbox 실행 검증 (미구현, Phase A)', implemented: false, hq: 'hq-9' },
      { name: 'UI Automation Specialist', role: 'PyAutoGUI/Playwright (미구현, Phase B)', implemented: false, hq: 'hq-9' },
      { name: 'Runtime Failure Analyzer', role: '실행 fail trace 분석 (미구현, Phase C)', implemented: false, hq: 'hq-9' },
      { name: 'Auto-Fix Coordinator', role: 'RV 재빌드 trigger (미구현, Phase C)', implemented: false, hq: 'hq-9' },
    ],
  },
  {
    key: 'hq-10',
    no: 10,
    label: 'Coordination',
    borderClass: 'border-purple-500/60',
    bgClass: 'bg-purple-950/25',
    accentClass: 'text-purple-300',
    charBgClass: 'bg-purple-300',
    pulseRgba: 'rgba(168, 85, 247, 0.5)',
    agents: [
      { name: 'Meeting Facilitator', role: '킥오프 회의 + shared assumptions', implemented: true, hq: 'hq-10' },
      { name: 'Retrospective Lead', role: '4-step 회고', implemented: true, hq: 'hq-10' },
      { name: 'Cross-Agent Consultant', role: '양방향 라우팅 (미구현, Phase 2)', implemented: false, hq: 'hq-10' },
      { name: 'Knowledge Curator (promoted)', role: '본부 5 → 본부 10 조직개편 (미구현, Phase 3)', implemented: false, hq: 'hq-10' },
    ],
  },
]

// telemetry.py 의 _NODE_DEPARTMENT 노드 → 본부 다중 매핑 (조직도 v12 기준)
const NODE_TO_HQS: Record<string, HQKey[]> = {
  expand_requirements: ['hq-1'],
  kickoff_meeting: ['hq-10'],
  analyze_gap: ['hq-1'],
  prepare_feedback: [],
  // run_chain: CTO + Engineer + Reviewer 다중 — 본부 0/3/4 동시 펄스
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

// =============================================================================
// 2. PixelCharacter — 16x16 grid + 8x8 face pattern + 구현/미구현 색상 분기
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
      className={`w-7 h-7 ${bobbing ? 'animate-bob' : ''} ${faded ? 'opacity-60' : ''}`}
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
// 3. App
// =============================================================================

const TOTAL_AGENTS = HEADQUARTERS.reduce((sum, h) => sum + h.agents.length, 0)
const IMPLEMENTED_AGENTS = HEADQUARTERS.reduce(
  (sum, h) => sum + h.agents.filter((a) => a.implemented).length,
  0,
)

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
  const [agentMessages, setAgentMessages] = useState<TelemetryEvent[]>([])

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

      // agent_status — 노드 → 본부 다중 매핑 → activeHqs 갱신
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

  // selectedAgent 의 부서가 active 면 전체 agent_messages, 아니면 빈 list
  // (telemetry agent_message 의 department 필드는 'planning/engineering/learning'
  //  3 중 하나라 11 본부 와 정확 매칭 어려움 — 일단 전체 표시)
  const selectedAgentMessages = selectedAgent ? agentMessages.slice(-20) : []

  return (
    <div className="h-screen w-screen flex flex-col bg-[#0d1117] text-slate-100">
      {/* ============ Top Toolbar ============ */}
      <header className="flex-shrink-0 border-b border-slate-800 bg-[#161b22]">
        <div className="px-6 py-2.5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-semibold text-slate-200">에이전트 오피스</span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-400">본부 {HEADQUARTERS.length}</span>
            <span className="text-slate-600">·</span>
            <span className="text-emerald-400 font-semibold">
              {IMPLEMENTED_AGENTS}/{TOTAL_AGENTS} 구현
            </span>
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

      {/* ============ Main 3-pane ============ */}
      <div className="flex-1 flex min-h-0">
        {/* === Sidebar === */}
        <aside className="w-[150px] flex-shrink-0 border-r border-slate-800 bg-[#161b22] flex flex-col">
          <div className="px-4 pt-4 pb-3 border-b border-slate-800">
            <div className="text-sm font-bold text-sky-400 leading-tight">Nexus Alpha</div>
            <div className="text-[10px] text-slate-500 leading-tight mt-0.5">
              Agent Office v11
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
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {HEADQUARTERS.map((hq) => {
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
                    <div className="grid grid-cols-3 gap-1.5 relative">
                      {hq.agents.map((agent) => {
                        const isSelected = selectedAgent?.name === agent.name
                        return (
                          <button
                            key={agent.name}
                            type="button"
                            onClick={() => setSelectedAgent(agent)}
                            className={`flex flex-col items-center gap-0.5 p-1 rounded transition hover:bg-slate-800/40 ${
                              isSelected ? 'ring-1 ring-sky-400 bg-slate-800/40' : ''
                            } ${!agent.implemented ? 'opacity-70' : ''}`}
                            title={`${agent.name}\n${agent.role}\n상태: ${agent.implemented ? (isActive ? 'working' : 'idle') : '미구현'}`}
                          >
                            <PixelCharacter
                              bgClass={hq.charBgClass}
                              bobbing={agent.implemented && isActive}
                              faded={!agent.implemented}
                            />
                            <span className="text-[8px] text-slate-200 leading-tight text-center line-clamp-2 break-words w-full">
                              {agent.name}
                            </span>
                            <span
                              className={`text-[7px] px-1 rounded ${
                                !agent.implemented
                                  ? 'bg-slate-700/60 text-slate-400 border border-slate-600'
                                  : isActive
                                    ? 'bg-emerald-700/40 text-emerald-300'
                                    : 'bg-slate-700/40 text-slate-400'
                              }`}
                            >
                              {!agent.implemented ? '미구현' : isActive ? 'working' : 'idle'}
                            </span>
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

        {/* === Right Detail Panel === */}
        <aside className="w-[220px] flex-shrink-0 border-l border-slate-800 bg-[#161b22] overflow-y-auto">
          {!selectedAgent ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-xs px-4 text-center">
              에이전트를 클릭하세요
            </div>
          ) : (
            <div className="p-4 space-y-3">
              <div>
                <h3 className="text-sm font-bold text-slate-100">{selectedAgent.name}</h3>
                <p className="text-[10px] text-slate-400 uppercase tracking-wide mt-0.5">
                  본부 {HEADQUARTERS.find((h) => h.key === selectedAgent.hq)?.no} ·{' '}
                  {HEADQUARTERS.find((h) => h.key === selectedAgent.hq)?.label}
                </p>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {!selectedAgent.implemented ? (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-slate-700/60 text-slate-300 border border-slate-600">
                    미구현
                  </span>
                ) : (
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded ${
                      activeHqs.has(selectedAgent.hq)
                        ? 'bg-emerald-700/40 text-emerald-300'
                        : 'bg-slate-700/40 text-slate-400'
                    }`}
                  >
                    {activeHqs.has(selectedAgent.hq) ? 'working' : 'idle'}
                  </span>
                )}
                {currentNodeByHq[selectedAgent.hq] && (
                  <span className="text-[10px] text-slate-400 font-mono truncate">
                    {currentNodeByHq[selectedAgent.hq]}
                  </span>
                )}
              </div>
              <div>
                <h4 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">
                  역할
                </h4>
                <p className="text-xs text-slate-300 leading-snug">{selectedAgent.role}</p>
              </div>
              <div>
                <h4 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">
                  대화 내역 ({selectedAgentMessages.length})
                </h4>
                <div className="space-y-1.5 max-h-[40vh] overflow-y-auto">
                  {selectedAgentMessages.length === 0 ? (
                    <p className="text-[10px] text-slate-500 italic">
                      {selectedAgent.implemented
                        ? '(LLM 호출 발생 시 표시됩니다)'
                        : '(미구현 에이전트 — 대화 없음)'}
                    </p>
                  ) : (
                    selectedAgentMessages.map((m, i) => (
                      <div
                        key={i}
                        className="border border-slate-800 rounded p-2 bg-slate-900/40 text-[10px] leading-snug"
                      >
                        <div className="flex items-center justify-between text-slate-500 text-[9px] mb-1">
                          <span>{m.role ?? 'llm_call'}</span>
                          <span>{m.ts?.slice(11, 19) ?? ''}</span>
                        </div>
                        <p className="text-slate-300 line-clamp-3 break-all">
                          {String(m.output_preview ?? m.prompt_preview ?? '').slice(0, 240)}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>

      {/* ============ Bottom Telemetry stream ============ */}
      <section className="flex-shrink-0 border-t border-slate-800 bg-[#161b22] p-2 max-h-[150px] flex flex-col">
        <div className="flex flex-wrap items-center gap-2 text-[10px] mb-1.5 px-1">
          <span className="font-semibold text-slate-200">Telemetry</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-400">
            <span className="text-slate-100 font-semibold">{lines.length}</span> line
          </span>
          <span className="text-blue-300">status {counts.agent_status}</span>
          <span className="text-purple-300">msg {counts.agent_message}</span>
          <span className="text-emerald-300">iter {counts.iteration_progress}</span>
          <span className="text-amber-300">result {counts.result}</span>
          <span className="text-slate-300">meta {counts.tail_meta}</span>
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
