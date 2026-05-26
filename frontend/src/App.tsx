import { useCallback, useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

// =============================================================================
// Sprint 6 UI 개편 — 3단 레이아웃 + 7 부서 Agent Office + 실시간 Telemetry 연동
// =============================================================================
//
// 레이아웃:
//   ┌─────────┬───────────────────────────┬──────────┐
//   │ Sidebar │ Toolbar                   │          │
//   │ (150px) ├───────────────────────────┤  Detail  │
//   │ menu    │ Agent Office (7 부서)      │  Panel   │
//   │ + 입력  │                           │  (220px) │
//   │         ├───────────────────────────┴──────────┤
//   │         │ Telemetry stream (counts + log)      │
//   └─────────┴──────────────────────────────────────┘
//
// Telemetry 연동 (src/monitoring/telemetry.py 의 _NODE_DEPARTMENT mirror):
//   agent_status (노드 단위)  → 해당 부서 카드 펄스 ON/OFF + agent bob
//   agent_message (LLM 호출) → 오른쪽 패널 대화 추가
//   result / run_end          → 시작 버튼 reset
//
// PM 요청 색상 매핑 (UI 차원):
//   C-Level         : 🟡 amber (금색)
//   PLANNING        : 🟣 purple (보라)
//   ENGINEERING     : 🟢 emerald (초록)
//   QA              : 🔴 red (빨강)
//   LEARNING        : 🟢 teal (청록)
//   DESIGN          : 🩷 pink (핑크/보라)
//   BUILD & RELEASE : 🟢 lime (연두)

// =============================================================================
// 1. 타입 + 상수 정의
// =============================================================================

type DeptKey =
  | 'c-level'
  | 'planning'
  | 'engineering'
  | 'qa'
  | 'learning'
  | 'design'
  | 'build-release'

interface AgentInfo {
  name: string
  role: string
  dept: DeptKey
}

interface DepartmentDef {
  key: DeptKey
  label: string
  borderClass: string
  bgClass: string
  accentClass: string
  pulseRgba: string
  agents: AgentInfo[]
}

const DEPARTMENTS: DepartmentDef[] = [
  {
    key: 'c-level',
    label: 'C-Level',
    borderClass: 'border-amber-500/60',
    bgClass: 'bg-amber-950/20',
    accentClass: 'text-amber-300',
    pulseRgba: 'rgba(245, 158, 11, 0.5)',
    agents: [
      { name: 'CTO', role: 'Chief Technology Officer — 기술 전략', dept: 'c-level' },
      { name: 'Convergence Judge', role: '결정론 verdict (COMPLETE/IMPROVE/BLOCKED)', dept: 'c-level' },
    ],
  },
  {
    key: 'planning',
    label: 'PLANNING',
    borderClass: 'border-purple-500/60',
    bgClass: 'bg-purple-950/25',
    accentClass: 'text-purple-300',
    pulseRgba: 'rgba(168, 85, 247, 0.5)',
    agents: [
      { name: 'Requirement Expander', role: '사용자 요청 YAML 확장', dept: 'planning' },
      { name: 'Meeting Facilitator', role: '킥오프 회의 + shared assumptions', dept: 'planning' },
      { name: 'Gap Analyst', role: 'iteration feedback gap 분석', dept: 'planning' },
      { name: 'Product Analyst', role: '제품 분석 + 사용자 시나리오', dept: 'planning' },
    ],
  },
  {
    key: 'engineering',
    label: 'ENGINEERING',
    borderClass: 'border-emerald-500/60',
    bgClass: 'bg-emerald-950/25',
    accentClass: 'text-emerald-300',
    pulseRgba: 'rgba(16, 185, 129, 0.5)',
    agents: [
      { name: 'Python Engineer', role: 'Senior Python 코드 생성', dept: 'engineering' },
      { name: 'GUI Code Generator', role: 'Tkinter/Flet/PyQt6 GUI 코드', dept: 'engineering' },
      { name: 'Code Reviewer', role: 'Static QA + Pydantic schema', dept: 'engineering' },
      { name: 'Sandbox Runner', role: '격리 subprocess 실행', dept: 'engineering' },
      { name: 'Build Engineer', role: 'PyInstaller .exe 빌드', dept: 'engineering' },
    ],
  },
  {
    key: 'qa',
    label: 'QA',
    borderClass: 'border-red-500/60',
    bgClass: 'bg-red-950/25',
    accentClass: 'text-red-300',
    pulseRgba: 'rgba(239, 68, 68, 0.5)',
    agents: [
      { name: 'Pytest Author', role: 'Pytest suite 생성 + 검증', dept: 'qa' },
      { name: 'Code QA', role: 'pytest + ruff 실행', dept: 'qa' },
      { name: 'GUI Test', role: 'pyautogui + Vision QA', dept: 'qa' },
      { name: 'Security QA', role: '취약점 스캔 + 권고', dept: 'qa' },
    ],
  },
  {
    key: 'learning',
    label: 'LEARNING',
    borderClass: 'border-teal-500/60',
    bgClass: 'bg-teal-950/25',
    accentClass: 'text-teal-300',
    pulseRgba: 'rgba(20, 184, 166, 0.5)',
    agents: [
      { name: 'RAG Searcher', role: '과거 workflow recall', dept: 'learning' },
      { name: 'Retrospective Lead', role: '4-step retrospective (well/wrong/lessons)', dept: 'learning' },
      { name: 'Knowledge Curator', role: 'YAML entry 큐레이션 + 인덱싱', dept: 'learning' },
      { name: 'Vision QA', role: 'GUI 스크린샷 LLM 검증 (옵션)', dept: 'learning' },
    ],
  },
  {
    key: 'design',
    label: 'DESIGN',
    borderClass: 'border-pink-500/60',
    bgClass: 'bg-pink-950/25',
    accentClass: 'text-pink-300',
    pulseRgba: 'rgba(236, 72, 153, 0.5)',
    agents: [
      { name: 'GUI Designer', role: '와이어프레임 + widget tree', dept: 'design' },
      { name: 'Theme Designer', role: 'Design tokens (palette/typography)', dept: 'design' },
    ],
  },
  {
    key: 'build-release',
    label: 'BUILD & RELEASE',
    borderClass: 'border-lime-500/60',
    bgClass: 'bg-lime-950/25',
    accentClass: 'text-lime-300',
    pulseRgba: 'rgba(132, 204, 22, 0.5)',
    agents: [
      { name: 'Installer', role: 'Windows installer (NSIS)', dept: 'build-release' },
      { name: 'Release Manager', role: 'GitHub release 코디네이션', dept: 'build-release' },
    ],
  },
]

// telemetry.py 의 _NODE_DEPARTMENT mirror — 노드 → UI 부서 매핑.
// PM 명시: finalize / escalate 는 SYSTEM 이라 펄스 X.
const NODE_TO_DEPT: Record<string, DeptKey | null> = {
  expand_requirements: 'planning',
  kickoff_meeting: 'planning',
  analyze_gap: 'planning',
  prepare_feedback: 'planning',
  run_chain: 'engineering',
  run_sandbox: 'engineering',
  recall_past_knowledge: 'learning',
  judge_convergence: 'learning',
  retrospective: 'learning',
  retrospective_blocked: 'learning',
  curate_knowledge: 'learning',
  curate_knowledge_blocked: 'learning',
  finalize: null,
  escalate: null,
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
const MAX_MESSAGES_PER_DEPT = 40

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
// 2. PixelCharacter — CSS grid 16x16 단순 face pattern
// =============================================================================
//
// 8x8 face pattern (1=색, 0=투명). 모든 부서 동일 design, 부서 색상으로 tint.

const FACE_PATTERN = [
  '0011110000111100'.split(''),
  '0111111001111110'.split(''),
  '1111111111111111'.split(''),
  '1111111111111111'.split(''),
  '1100110011001100'.split(''), // 눈 line 1
  '1100110011001100'.split(''), // 눈 line 2
  '1111111111111111'.split(''),
  '1111111111111111'.split(''),
  '1111111111111111'.split(''),
  '1110000000000111'.split(''), // 입 line 1
  '1111000000001111'.split(''), // 입 line 2
  '1111111111111111'.split(''),
  '1111111111111111'.split(''),
  '0111111111111110'.split(''),
  '0011111111111100'.split(''),
  '0000111111110000'.split(''),
]

interface PixelCharacterProps {
  bgClass: string // tailwind bg color class (e.g. 'bg-emerald-400')
  bobbing: boolean
}

function PixelCharacter({ bgClass, bobbing }: PixelCharacterProps) {
  return (
    <div
      className={`grid grid-cols-16 grid-rows-16 w-8 h-8 ${bobbing ? 'animate-bob' : ''}`}
      style={{ gridTemplateColumns: 'repeat(16, minmax(0, 1fr))', gridTemplateRows: 'repeat(16, minmax(0, 1fr))' }}
      aria-hidden
    >
      {FACE_PATTERN.flat().map((cell, i) => (
        <div key={i} className={cell === '1' ? bgClass : ''} />
      ))}
    </div>
  )
}

// 부서별 character bg color (Tailwind class)
const DEPT_CHAR_BG: Record<DeptKey, string> = {
  'c-level': 'bg-amber-300',
  planning: 'bg-purple-300',
  engineering: 'bg-emerald-300',
  qa: 'bg-red-300',
  learning: 'bg-teal-300',
  design: 'bg-pink-300',
  'build-release': 'bg-lime-300',
}

// =============================================================================
// 3. App
// =============================================================================

function App() {
  // -- state --
  const [request, setRequest] = useState('')
  const [running, setRunning] = useState(false)
  const [eventsPath, setEventsPath] = useState<string | null>(null)
  const [lines, setLines] = useState<CapturedLine[]>([])
  const [error, setError] = useState<string | null>(null)
  const [auth, setAuth] = useState<AuthStatus>(EMPTY_AUTH)
  const [authLoading, setAuthLoading] = useState<boolean>(true)
  const [activeDepts, setActiveDepts] = useState<Set<DeptKey>>(new Set())
  const [selectedAgent, setSelectedAgent] = useState<AgentInfo | null>(null)
  const [activeMenu, setActiveMenu] = useState<MenuKey>('agent-map')
  const [messagesByDept, setMessagesByDept] = useState<Record<string, TelemetryEvent[]>>({})
  const [currentNodeByDept, setCurrentNodeByDept] = useState<Record<string, string>>({})

  // -- helpers --
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

  // -- telemetry listener --
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

      // 1) lines stream 누적
      setLines((prev) => {
        const captured: CapturedLine = { raw, parsed, receivedAt: new Date().toISOString() }
        const next = [...prev, captured]
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next
      })

      // 2) agent_status — 노드 → 부서 매핑 → activeDepts 갱신
      if (parsed?.type === 'agent_status' && parsed.agent) {
        const deptKey = NODE_TO_DEPT[parsed.agent] ?? null
        if (deptKey) {
          setActiveDepts((prev) => {
            const next = new Set(prev)
            if (parsed.status === 'working') {
              next.add(deptKey)
            } else if (parsed.status === 'done' || parsed.status === 'error') {
              next.delete(deptKey)
            }
            return next
          })
          if (parsed.status === 'working') {
            setCurrentNodeByDept((prev) => ({ ...prev, [deptKey]: parsed.agent! }))
          } else if (parsed.status === 'done' || parsed.status === 'error') {
            setCurrentNodeByDept((prev) => {
              const next = { ...prev }
              if (next[deptKey] === parsed.agent) delete next[deptKey]
              return next
            })
          }
        }
      }

      // 3) agent_message — 부서별 누적 (department 필드 기준)
      if (parsed?.type === 'agent_message' && parsed.department) {
        const dept = String(parsed.department)
        setMessagesByDept((prev) => {
          const cur = prev[dept] ?? []
          const next = [...cur, parsed]
          return {
            ...prev,
            [dept]: next.length > MAX_MESSAGES_PER_DEPT ? next.slice(-MAX_MESSAGES_PER_DEPT) : next,
          }
        })
      }

      // 4) result / run_end — 시작 버튼 reset
      if (
        parsed?.type === 'result' ||
        (parsed?.type === 'iteration_progress' && parsed.phase === 'run_end')
      ) {
        setRunning(false)
        setActiveDepts(new Set())
        setCurrentNodeByDept({})
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

  // -- counts --
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

  // -- handlers --
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
    setMessagesByDept({})
    setActiveDepts(new Set())
    setCurrentNodeByDept({})
    try {
      const path = await invoke<string>('start_run', {
        request,
        track: 'A',
        build: false,
        maxIterations: 1,
      })
      setEventsPath(path)
      // eslint-disable-next-line no-console
      console.log('[Tauri] sidecar started, events.jsonl =', path)
    } catch (e) {
      const msg = String(e ?? 'unknown')
      setError(msg)
      setRunning(false)
      // eslint-disable-next-line no-console
      console.error('[Tauri] start_run 실패', e)
    }
  }

  const handleLogin = async () => {
    setError(null)
    try {
      const status = await invoke<AuthStatus>('claude_auth_login')
      setAuth(status)
    } catch (e) {
      const msg = String(e ?? 'unknown')
      // eslint-disable-next-line no-console
      console.error('[Auth] login 실패', e)
      setError(`로그인 실패: ${msg}`)
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
      const errMsg = String(e ?? 'unknown')
      // eslint-disable-next-line no-console
      console.error('[Auth] logout 실패', e)
      setError(`로그아웃 실패: ${errMsg}`)
    }
  }

  const selectedDeptMessages = selectedAgent
    ? messagesByDept[selectedAgent.dept] ?? []
    : []

  const totalActive = DEPARTMENTS.reduce((sum, d) => sum + d.agents.length, 0)

  // =============================================================================
  // Render
  // =============================================================================
  return (
    <div className="h-screen w-screen flex flex-col bg-[#0d1117] text-slate-100">
      {/* ============ 1. Top Toolbar ============ */}
      <header className="flex-shrink-0 border-b border-slate-800 bg-[#161b22]">
        <div className="px-6 py-2.5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-semibold text-slate-200">에이전트 오피스</span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-400">본부 11</span>
            <span className="text-slate-600">·</span>
            <span className="text-emerald-400 font-semibold">{totalActive} active</span>
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
                  <span className="px-2 py-0.5 rounded bg-emerald-600/30 border border-emerald-500/60 text-emerald-200 text-xs font-bold tracking-wide">
                    MAX
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="ml-1 px-3 py-1 rounded-md border border-slate-600 hover:border-slate-400 text-slate-200 hover:text-white text-xs transition"
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
                  className="ml-1 px-3 py-1 rounded-md bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold transition"
                >
                  로그인
                </button>
              </>
            )}
          </div>
        </div>
        {auth.error && !authLoading && (
          <div className="px-6 pb-2 text-xs text-amber-400">
            <strong>auth status:</strong> {auth.error}
          </div>
        )}
      </header>

      {/* ============ Main 3-pane ============ */}
      <div className="flex-1 flex min-h-0">
        {/* === Left Sidebar === */}
        <aside className="w-[150px] flex-shrink-0 border-r border-slate-800 bg-[#161b22] flex flex-col">
          {/* 로고 + 부제 */}
          <div className="px-4 pt-4 pb-3 border-b border-slate-800">
            <div className="text-sm font-bold text-sky-400 leading-tight">Nexus Alpha</div>
            <div className="text-[10px] text-slate-500 leading-tight mt-0.5">
              Agent Office v11
            </div>
          </div>

          {/* 메뉴 */}
          <nav className="flex-1 overflow-y-auto py-2">
            {MENU_ITEMS.map((m) => {
              const isActive = activeMenu === m.key
              return (
                <button
                  key={m.key}
                  type="button"
                  onClick={() => m.enabled && setActiveMenu(m.key)}
                  disabled={!m.enabled}
                  className={`w-full text-left px-3 py-2 text-xs transition border-l-2 ${
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

          {/* 하단 고정 자연어 입력창 */}
          <div className="flex-shrink-0 border-t border-slate-800 p-3 space-y-2">
            <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
              자연어 요청
            </label>
            <textarea
              rows={3}
              className="w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 resize-none"
              placeholder="예: 칸반 보드 앱 만들어줘"
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              disabled={running}
            />
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={running || !request.trim()}
              className="w-full px-2 py-1.5 bg-sky-600 hover:bg-sky-500 active:bg-sky-700 disabled:bg-slate-700 disabled:text-slate-500 rounded text-xs font-semibold transition"
            >
              {running ? '실행 중…' : '시작'}
            </button>
            {error && <p className="text-[10px] text-red-400 break-words">{error}</p>}
            {eventsPath && (
              <p className="text-[9px] text-slate-500 break-all" title={eventsPath}>
                events.jsonl: …{eventsPath.slice(-30)}
              </p>
            )}
          </div>
        </aside>

        {/* === Center Agent Office === */}
        <main className="flex-1 min-w-0 overflow-y-auto p-4 bg-[#0d1117]">
          {activeMenu !== 'agent-map' ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm">
              "{MENU_ITEMS.find((m) => m.key === activeMenu)?.label}" 메뉴는 준비 중입니다.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {DEPARTMENTS.map((dept) => {
                const isActive = activeDepts.has(dept.key)
                const currentNode = currentNodeByDept[dept.key]
                return (
                  <section
                    key={dept.key}
                    className={`relative border-2 ${dept.borderClass} ${dept.bgClass} rounded-xl p-3`}
                    style={
                      isActive
                        ? ({ '--pulse-color': dept.pulseRgba } as React.CSSProperties)
                        : undefined
                    }
                  >
                    {/* dept 펄스 ring (active 일 때만) */}
                    {isActive && (
                      <div
                        className="absolute inset-0 rounded-xl pointer-events-none animate-dept-pulse"
                        style={{ '--pulse-color': dept.pulseRgba } as React.CSSProperties}
                      />
                    )}
                    <header className="flex items-center justify-between mb-2 relative">
                      <h2 className={`text-xs font-bold tracking-wide ${dept.accentClass}`}>
                        {dept.label}
                      </h2>
                      {isActive && currentNode && (
                        <span className="text-[9px] text-slate-400 font-mono truncate ml-2">
                          {currentNode}
                        </span>
                      )}
                    </header>
                    <div className="grid grid-cols-2 gap-2 relative">
                      {dept.agents.map((agent) => {
                        const isSelected = selectedAgent?.name === agent.name
                        return (
                          <button
                            key={agent.name}
                            type="button"
                            onClick={() => setSelectedAgent(agent)}
                            className={`flex flex-col items-center gap-1 p-1.5 rounded transition hover:bg-slate-800/40 ${
                              isSelected ? 'ring-1 ring-sky-400 bg-slate-800/40' : ''
                            }`}
                            title={`${agent.name}\n${agent.role}\n상태: ${isActive ? 'working' : 'idle'}`}
                          >
                            <PixelCharacter bgClass={DEPT_CHAR_BG[dept.key]} bobbing={isActive} />
                            <span className="text-[9px] text-slate-200 leading-tight text-center line-clamp-2">
                              {agent.name}
                            </span>
                            <span
                              className={`text-[8px] px-1 rounded ${
                                isActive
                                  ? 'bg-emerald-700/40 text-emerald-300'
                                  : 'bg-slate-700/40 text-slate-400'
                              }`}
                            >
                              {isActive ? 'working' : 'idle'}
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
                  {DEPARTMENTS.find((d) => d.key === selectedAgent.dept)?.label}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`text-[10px] px-2 py-0.5 rounded ${
                    activeDepts.has(selectedAgent.dept)
                      ? 'bg-emerald-700/40 text-emerald-300'
                      : 'bg-slate-700/40 text-slate-400'
                  }`}
                >
                  {activeDepts.has(selectedAgent.dept) ? 'working' : 'idle'}
                </span>
                {currentNodeByDept[selectedAgent.dept] && (
                  <span className="text-[10px] text-slate-400 font-mono truncate">
                    {currentNodeByDept[selectedAgent.dept]}
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
                  대화 내역 ({selectedDeptMessages.length})
                </h4>
                <div className="space-y-1.5 max-h-[40vh] overflow-y-auto">
                  {selectedDeptMessages.length === 0 ? (
                    <p className="text-[10px] text-slate-500 italic">
                      (이 부서의 LLM 호출이 발생하면 여기 표시됩니다)
                    </p>
                  ) : (
                    selectedDeptMessages.map((m, i) => (
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
      <section className="flex-shrink-0 border-t border-slate-800 bg-[#161b22] p-2 max-h-[180px] flex flex-col">
        <div className="flex flex-wrap items-center gap-2 text-[10px] mb-1.5 px-1">
          <span className="font-semibold text-slate-200">Telemetry stream</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-400">
            총 <span className="text-slate-100 font-semibold">{lines.length}</span>
          </span>
          <span className="text-blue-300">agent_status {counts.agent_status}</span>
          <span className="text-purple-300">agent_message {counts.agent_message}</span>
          <span className="text-emerald-300">iter_prog {counts.iteration_progress}</span>
          <span className="text-amber-300">result {counts.result}</span>
          <span className="text-slate-300">tail_meta {counts.tail_meta}</span>
          {counts.unknown > 0 && <span className="text-slate-400">? {counts.unknown}</span>}
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
