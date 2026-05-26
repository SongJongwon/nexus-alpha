import { useCallback, useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

/**
 * Sprint 5 이후 PR — Claude Code CLI 인증 통합 + sticky toolbar.
 *
 * 추가 변경:
 *   1. Sticky 툴바 (top, z-50) — 로고 + 인증 상태 (🟢/🔴 + 이메일 + MAX 뱃지) + 로그인/로그아웃 버튼.
 *   2. 앱 시작 시 invoke('claude_auth_status') → 자동 인증 상태 표시.
 *   3. 로그아웃: 확인 다이얼로그 (진행 중 작업 있으면 경고 강화) → invoke('claude_auth_logout') → 상태 갱신.
 *   4. 시작 버튼: 로그인 안된 경우 "Claude 로그인 필요" 안내 + 시작 차단.
 *   5. start_run 호출은 Rust 측에서 자동으로 --force-cli 기본 추가 (PM 요청).
 */

type DeptKey = 'planning' | 'engineering' | 'learning'

interface DeptCard {
  key: DeptKey
  emoji: string
  label: string
  borderClass: string
  bgClass: string
  ringClass: string
  agents: string[]
  description: string
}

const DEPARTMENTS: DeptCard[] = [
  {
    key: 'planning',
    emoji: '🔵',
    label: '기획 부서',
    borderClass: 'border-blue-500/50',
    bgClass: 'bg-blue-950/30',
    ringClass: 'ring-blue-400',
    agents: [
      'Requirement Expander',
      'Meeting Facilitator',
      'Gap Analyst',
      'CTO',
      'Product Analyst',
    ],
    description: '회의 / 분석 / feedback 작성',
  },
  {
    key: 'engineering',
    emoji: '🟣',
    label: '개발 부서',
    borderClass: 'border-purple-500/50',
    bgClass: 'bg-purple-950/30',
    ringClass: 'ring-purple-400',
    agents: [
      'Python Engineer',
      'Code Reviewer',
      'Sandbox Runner',
      'Pytest Author',
      'GUI Code Generator',
      'Build Engineer',
    ],
    description: '코드 작성 / 실행',
  },
  {
    key: 'learning',
    emoji: '🟢',
    label: '학습 부서',
    borderClass: 'border-emerald-500/50',
    bgClass: 'bg-emerald-950/30',
    ringClass: 'ring-emerald-400',
    agents: [
      'Curator + RAG Searcher',
      'Retrospective Lead',
      'Convergence Judge',
      'Vision QA',
    ],
    description: '회고 / RAG / 결정표',
  },
]

interface TelemetryEvent {
  type?: string
  agent?: string
  department?: string
  status?: string
  phase?: string
  verdict?: string
  ts?: string
  [k: string]: unknown
}

interface CapturedLine {
  raw: string
  parsed: TelemetryEvent | null
  receivedAt: string
}

interface AuthStatus {
  logged_in: boolean
  email: string | null
  subscription_type: string | null
  auth_method: string | null
  org_name: string | null
  error: string | null
}

const EMPTY_AUTH: AuthStatus = {
  logged_in: false,
  email: null,
  subscription_type: null,
  auth_method: null,
  org_name: null,
  error: null,
}

const MAX_LINES = 200

function App() {
  const [request, setRequest] = useState('')
  const [activeDept, setActiveDept] = useState<DeptKey | null>(null)
  const [running, setRunning] = useState(false)
  const [eventsPath, setEventsPath] = useState<string | null>(null)
  const [lines, setLines] = useState<CapturedLine[]>([])
  const [error, setError] = useState<string | null>(null)
  const [auth, setAuth] = useState<AuthStatus>(EMPTY_AUTH)
  const [authLoading, setAuthLoading] = useState<boolean>(true)

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

  // 앱 시작 시 자동 인증 조회 + telemetry listener 등록.
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
        const captured: CapturedLine = {
          raw,
          parsed,
          receivedAt: new Date().toISOString(),
        }
        const next = [...prev, captured]
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next
      })
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
    if (!auth.logged_in) {
      setError('Claude 로그인이 필요합니다. 우측 상단 [로그인] 버튼을 눌러주세요.')
      return
    }
    setError(null)
    setRunning(true)
    setLines([])
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 to-slate-900 text-slate-100">
      {/* ============ 1. Sticky 툴바 ============ */}
      <header className="sticky top-0 z-50 backdrop-blur-md bg-slate-950/85 border-b border-slate-800">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-sky-400">Nexus Alpha</span>
            <span className="text-xs text-slate-500 hidden sm:inline">Agent Office</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {authLoading ? (
              <>
                <span className="w-2 h-2 rounded-full bg-slate-500 animate-pulse" aria-hidden />
                <span className="text-slate-400">인증 상태 확인 중…</span>
              </>
            ) : auth.logged_in ? (
              <>
                <span
                  className="w-2 h-2 rounded-full bg-emerald-500"
                  aria-label="Claude Code 로그인 됨"
                />
                <span className="text-slate-200 max-w-[16rem] truncate" title={auth.email ?? ''}>
                  {auth.email ?? '(이메일 없음)'}
                </span>
                {auth.subscription_type?.toLowerCase() === 'max' && (
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
                <span
                  className="w-2 h-2 rounded-full bg-red-500"
                  aria-label="Claude Code 로그인 안 됨"
                />
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
          <div className="max-w-6xl mx-auto px-6 pb-2 text-xs text-amber-400">
            <strong>auth status 경고:</strong> {auth.error}
          </div>
        )}
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        <section>
          <h1 className="text-2xl font-bold text-sky-400 mb-1">Agent Office</h1>
          <p className="text-slate-400 text-sm">
            자연어 → .exe 풀체인 자기 진화 cycle 의 사용자 가시화 layer. 본 PR
            에서 Claude Code CLI 인증 통합 + sticky toolbar 추가.
          </p>
        </section>

        <section>
          <label className="block text-slate-300 mb-2 text-sm font-semibold">
            자연어 요청{' '}
            <span className="text-slate-500 font-normal">
              (Tauri command `start_run` + Python sidecar — Claude Code 구독 기반)
            </span>
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              className="flex-1 px-4 py-3 bg-slate-800/80 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 transition"
              placeholder="예: 계산기 만들어줘"
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              disabled={running}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleStart()
              }}
            />
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={running || !request.trim()}
              className="px-6 py-3 bg-sky-600 hover:bg-sky-500 active:bg-sky-700 disabled:bg-slate-700 disabled:text-slate-500 rounded-lg font-semibold transition"
            >
              {running ? '실행 중…' : '시작'}
            </button>
          </div>
          {error && (
            <p className="mt-2 text-sm text-red-400">
              <strong>오류:</strong> {error}
            </p>
          )}
          {eventsPath && (
            <p className="mt-2 text-xs text-slate-500">
              events.jsonl:{' '}
              <code className="px-1 bg-slate-800 rounded text-slate-400">{eventsPath}</code>
            </p>
          )}
        </section>

        <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {DEPARTMENTS.map((dept) => {
            const isActive = activeDept === dept.key
            return (
              <button
                key={dept.key}
                type="button"
                onClick={() => setActiveDept(isActive ? null : dept.key)}
                className={`text-left p-5 border-2 ${dept.borderClass} ${dept.bgClass} rounded-xl transition-all hover:scale-[1.02] hover:border-slate-300/80 ${
                  isActive ? `ring-2 ring-offset-2 ring-offset-slate-900 ${dept.ringClass}` : ''
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-2xl">{dept.emoji}</span>
                  <h2 className="text-lg font-bold text-slate-100">{dept.label}</h2>
                </div>
                <p className="text-sm text-slate-300 mb-3">{dept.description}</p>
                <ul className="space-y-1">
                  {dept.agents.map((agent) => (
                    <li key={agent} className="text-xs text-slate-400">
                      • {agent}
                    </li>
                  ))}
                </ul>
              </button>
            )
          })}
        </section>

        <section className="border border-slate-700 rounded-xl p-4 bg-slate-900/60">
          <div className="flex flex-wrap items-center gap-3 mb-3 text-sm">
            <span className="font-semibold text-slate-200">Telemetry stream</span>
            <span className="text-slate-500">·</span>
            <span className="text-slate-400">
              총 <span className="text-slate-100 font-semibold">{lines.length}</span> line
            </span>
            <span className="text-slate-500">·</span>
            <span className="text-blue-300">agent_status {counts.agent_status}</span>
            <span className="text-purple-300">agent_message {counts.agent_message}</span>
            <span className="text-emerald-300">iteration_progress {counts.iteration_progress}</span>
            <span className="text-amber-300">result {counts.result}</span>
            {counts.unknown > 0 && (
              <span className="text-slate-400">unknown {counts.unknown}</span>
            )}
          </div>
          <pre className="h-64 overflow-auto text-xs font-mono text-slate-300 bg-slate-950/60 rounded-lg p-3 leading-relaxed">
            {lines.length === 0
              ? '// (시작 버튼을 누르면 Python sidecar 의 events.jsonl 이 tail 됩니다)'
              : lines
                  .map((l) =>
                    l.parsed
                      ? `[${l.parsed.type ?? '?'}] ${l.parsed.agent ?? l.parsed.phase ?? l.parsed.verdict ?? ''}  ${l.parsed.status ?? ''}`.trim()
                      : `[raw] ${l.raw}`,
                  )
                  .join('\n')}
          </pre>
        </section>

        <footer className="p-4 border border-dashed border-slate-700 rounded-lg text-sm text-slate-400">
          <strong className="text-slate-300">Sprint 6 도착 후:</strong> 본 panel
          의 line 들은 부서 카드의 펄스 / 대화 panel 의 말풍선 / iteration progress
          바로 시각화. 본 PR 은 인증 + 시작 흐름의 baseline.
        </footer>
      </main>
    </div>
  )
}

export default App
