import { useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

/**
 * Sprint 5 PR-C — Agent Office Visualizer 의 *실제 sidecar wire layer*.
 *
 * PR-B 는 정적 부서 그리드 placeholder, **본 PR-C** 는:
 *   1. 자연어 입력창 + 시작 버튼 → Rust `start_run` command invoke.
 *   2. Rust 의 tail thread 가 emit 한 `nexus://telemetry` event 수신
 *      (events.jsonl 한 line 당 한 event) → 콘솔 log + 화면 panel 렌더.
 *   3. event type 별 카운터 (`agent_status` / `agent_message` /
 *      `iteration_progress` / `result`) 로 PR #188 Sprint 4 의 4 event type
 *      수신 가시화.
 *
 * 본 PR 시점 한계:
 *   - 카드 펄스 / working 강조 / 대화 panel 의 *부서별 매핑* 은 Sprint 6 시각화 단계.
 *   - run 중단 / 재실행 / 다중 run 동시 처리는 PR-C 이후 follow-up.
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

const MAX_LINES = 200

function App() {
  const [request, setRequest] = useState('')
  const [activeDept, setActiveDept] = useState<DeptKey | null>(null)
  const [running, setRunning] = useState(false)
  const [eventsPath, setEventsPath] = useState<string | null>(null)
  const [lines, setLines] = useState<CapturedLine[]>([])
  const [error, setError] = useState<string | null>(null)

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
      // PR-C 검증 목적의 콘솔 log — sprint 5 가이드의 "4 event type 콘솔 log" 요구
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
    if (!request.trim() || running) return
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 to-slate-900 text-slate-100 p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        <header>
          <h1 className="text-3xl font-bold text-sky-400 mb-1">
            Nexus Alpha — Agent Office
          </h1>
          <p className="text-slate-400 text-sm">
            Sprint 5 PR-C — Python sidecar spawn + JSON Lines tail + 4 event
            type 콘솔 log. Sprint 6 에서 부서 펄스 / 대화 panel 시각화.
          </p>
        </header>

        <section>
          <label className="block text-slate-300 mb-2 text-sm font-semibold">
            자연어 요청{' '}
            <span className="text-slate-500 font-normal">
              (Tauri command `start_run` 으로 Python sidecar 실행)
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
              <strong>start_run 실패:</strong> {error}
            </p>
          )}
          {eventsPath && (
            <p className="mt-2 text-xs text-slate-500">
              events.jsonl: <code className="px-1 bg-slate-800 rounded text-slate-400">{eventsPath}</code>
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
          <strong className="text-slate-300">Sprint 6 도착 후:</strong> 본
          panel 의 line 들은 부서 카드의 펄스 / 대화 panel 의 말풍선 / iteration
          progress 바로 *시각화*. 본 PR-C 는 stream 수신 자체의 검증.
        </footer>
      </div>
    </div>
  )
}

export default App
