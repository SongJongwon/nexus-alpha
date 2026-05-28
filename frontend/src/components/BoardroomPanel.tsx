// =============================================================================
// BoardroomPanel — v13 Phase 5.1 (PR #223)
// =============================================================================
//
// Phase 4 (PR #222) 의 산출물 (decision.yaml + 회의록 markdown) 시각화 panel.
//
// 레이아웃 (PM 사전 승인 — 3단 고정):
//   ┌─────────────┬───────────────────────────────┬──────────┐
//   │ 세션 list   │  decision.yaml viewer         │ 회의록   │
//   │ (사이드바)  │  alignment / budget / final   │ markdown │
//   │ timestamp   │  카드 3개 색상 강조           │ raw 본문 │
//   │ desc 최근   │  (amber/blue/emerald|red)     │          │
//   │ 50건        │                               │          │
//   └─────────────┴───────────────────────────────┴──────────┘
//
// Tauri commands:
//   list_board_decisions     — outputs/board_decisions/*/decision.yaml list
//   read_board_decision      — decision.yaml 의 JSON 파싱 결과
//   list_boardroom_sessions  — outputs/_boardroom_sessions/*.md list (cross-ref)
//   read_boardroom_session   — 회의록 markdown 원문
//
// 자동 갱신: 30초마다 list 재조회 (자율 진화 cycle 진행 중 신규 의결 가시화).

import { useCallback, useEffect, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'

// =============================================================================
// 1. 타입 정의 — decision.yaml schema v1 (Phase 4 PR #222)
// =============================================================================

export interface BoardroomListItem {
  name: string
  timestamp: string
  session_id: string
  path: string
}

interface AlignmentSection {
  status?: string
  reason?: string
  references?: string[]
  checked_at?: string
}

interface BudgetSection {
  status?: string
  estimated_cost_usd?: number | null
  budget_limit_usd?: number | null
  cumulative_cost_usd?: number | null
  reason?: string
  checked_at?: string
}

interface FinalDecisionSection {
  outcome?: string
  reason?: string
  blocked_by?: string[]
  decided_at?: string
}

interface SessionSection {
  session_id?: string
  agenda?: string
  proposal_path?: string | null
  opened_at?: string
  closed_at?: string
  attendees?: string[]
}

// v13 Phase 5.4 (PR #224) — Statement + Round schema
interface StatementSection {
  agent?: string
  role?: string  // proposer / reviewer / dissenter / mediator
  content?: string
  timestamp?: string
}

interface RoundSection {
  round_num?: number
  started_at?: string
  ended_at?: string
  dissent_detected?: boolean
  statements?: StatementSection[]
}

interface DecisionYaml {
  schema_version?: string  // "v1" (Phase 4) | "v2" (Phase 5.4)
  session?: SessionSection
  alignment?: AlignmentSection | null
  budget?: BudgetSection | null
  final_decision?: FinalDecisionSection | null
  // v2 신규 (v1 yaml 에서는 undefined 또는 빈 list)
  rounds?: RoundSection[]
  consensus?: string | null
}

// =============================================================================
// 2. helpers
// =============================================================================

const POLL_INTERVAL_MS = 30_000

function formatTimestamp(iso?: string): string {
  if (!iso) return '?'
  // "2026-05-28T12:00:00Z" → "05-28 12:00"
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  if (!m) return iso
  return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`
}

function outcomeBadgeClasses(outcome?: string): string {
  if (outcome === 'approved') {
    return 'bg-emerald-900/40 text-emerald-300 border-emerald-700'
  }
  if (outcome === 'blocked') {
    return 'bg-red-900/40 text-red-300 border-red-700'
  }
  return 'bg-slate-800 text-slate-400 border-slate-700'
}

function statusBadgeClasses(status?: string): string {
  if (status === 'approved') {
    return 'bg-emerald-900/40 text-emerald-300 border-emerald-700'
  }
  if (status === 'rejected' || status === 'throttled') {
    return 'bg-red-900/40 text-red-300 border-red-700'
  }
  return 'bg-slate-800 text-slate-400 border-slate-700'
}

// =============================================================================
// 3. 컴포넌트
// =============================================================================

export function BoardroomPanel() {
  const [decisions, setDecisions] = useState<BoardroomListItem[]>([])
  const [sessions, setSessions] = useState<BoardroomListItem[]>([])
  const [selected, setSelected] = useState<BoardroomListItem | null>(null)
  const [decisionYaml, setDecisionYaml] = useState<DecisionYaml | null>(null)
  const [sessionMd, setSessionMd] = useState<string>('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloading, setReloading] = useState(false)

  const reloadLists = useCallback(async () => {
    setReloading(true)
    try {
      const [d, s] = await Promise.all([
        invoke<BoardroomListItem[]>('list_board_decisions'),
        invoke<BoardroomListItem[]>('list_boardroom_sessions'),
      ])
      setDecisions(d)
      setSessions(s)
      setLoadError(null)
    } catch (e) {
      setLoadError(String(e))
    } finally {
      setReloading(false)
    }
  }, [])

  // 초기 + 30초 주기 폴링 — setState in effect 는 의도된 폴링 패턴
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reloadLists()
    const t = setInterval(() => void reloadLists(), POLL_INTERVAL_MS)
    return () => clearInterval(t)
  }, [reloadLists])

  // selected 변경 시 decision.yaml + 회의록 fetch
  useEffect(() => {
    if (!selected) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDecisionYaml(null)
      setSessionMd('')
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const yaml = await invoke<DecisionYaml>('read_board_decision', {
          name: selected.name,
        })
        if (!cancelled) setDecisionYaml(yaml)
      } catch (e) {
        if (!cancelled) {
          setDecisionYaml(null)
          setLoadError(`decision.yaml 읽기 실패: ${String(e)}`)
        }
      }
      // 회의록 (session_id 일치하는 markdown) 찾기
      const match = sessions.find((s) => s.session_id === selected.session_id)
      if (match) {
        try {
          const text = await invoke<string>('read_boardroom_session', {
            name: match.name,
          })
          if (!cancelled) setSessionMd(text)
        } catch {
          if (!cancelled) setSessionMd('(회의록 markdown 읽기 실패)')
        }
      } else {
        if (!cancelled) setSessionMd('(동일 session_id 회의록 미발견)')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selected, sessions])

  return (
    <div className="flex h-full min-h-0 bg-[#0d1117] text-slate-200">
      {/* === Left: 세션 list === */}
      <aside className="w-[220px] flex-shrink-0 border-r border-slate-800 flex flex-col">
        <div className="px-3 py-2 border-b border-slate-800 flex items-center justify-between">
          <div>
            <div className="text-xs font-bold text-amber-300">의결 로그</div>
            <div className="text-[9px] text-slate-500">
              outputs/board_decisions/
            </div>
          </div>
          <button
            type="button"
            onClick={() => void reloadLists()}
            disabled={reloading}
            className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-50"
            title="목록 새로고침"
          >
            {reloading ? '…' : '↻'}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {decisions.length === 0 ? (
            <div className="p-3 text-[11px] text-slate-500 leading-relaxed">
              {loadError ? (
                <>
                  <div className="text-red-400 font-semibold mb-1">로드 실패</div>
                  <div className="break-words">{loadError}</div>
                </>
              ) : (
                <>
                  아직 의결 로그가 없습니다.
                  <br />
                  <br />
                  자율 진화 루프가 1회 cycle 완주하면 자동 생성됩니다 (RV
                  silent fail 5회 → Strategist → Boardroom 의결).
                </>
              )}
            </div>
          ) : (
            <ul className="py-1">
              {decisions.map((d) => {
                const isSelected = selected?.name === d.name
                return (
                  <li key={d.name}>
                    <button
                      type="button"
                      onClick={() => setSelected(d)}
                      className={`w-full text-left px-3 py-2 text-[11px] border-l-2 transition ${
                        isSelected
                          ? 'border-amber-500 bg-amber-500/10 text-amber-200'
                          : 'border-transparent text-slate-300 hover:bg-slate-800/50 hover:border-slate-600'
                      }`}
                    >
                      <div className="font-mono text-[10px] text-slate-400">
                        {formatTimestamp(d.timestamp)}
                      </div>
                      <div className="font-mono text-[10px] text-slate-500 truncate">
                        {d.session_id}
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </aside>

      {/* === Center: decision.yaml viewer === */}
      <main className="flex-1 min-w-0 overflow-y-auto p-4">
        {!selected ? (
          <div className="h-full flex items-center justify-center text-slate-500 text-sm">
            왼쪽 목록에서 의결 로그를 선택하세요.
          </div>
        ) : !decisionYaml ? (
          <div className="text-slate-500 text-sm">decision.yaml 로딩 중…</div>
        ) : (
          <DecisionViewer data={decisionYaml} />
        )}
      </main>

      {/* === Right: 회의록 markdown === */}
      <aside className="w-[320px] flex-shrink-0 border-l border-slate-800 flex flex-col">
        <div className="px-3 py-2 border-b border-slate-800">
          <div className="text-xs font-bold text-purple-300">회의록</div>
          <div className="text-[9px] text-slate-500">
            outputs/_boardroom_sessions/
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {selected ? (
            <pre className="text-[10px] text-slate-300 whitespace-pre-wrap font-mono leading-relaxed">
              {sessionMd || '(읽기 중…)'}
            </pre>
          ) : (
            <div className="text-[11px] text-slate-500">
              의결 로그 선택 시 동일 session_id 의 회의록 markdown 을 표시합니다.
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}

// =============================================================================
// 4. DecisionViewer — 3 섹션 카드
// =============================================================================

function DecisionViewer({ data }: { data: DecisionYaml }) {
  const session = data.session ?? {}
  const alignment = data.alignment ?? null
  const budget = data.budget ?? null
  const final = data.final_decision ?? null
  const rounds = data.rounds ?? []
  const consensus = data.consensus ?? null
  const isV2 = data.schema_version === 'v2'

  return (
    <div className="space-y-3 text-sm">
      {/* ============ Header — session 메타 ============ */}
      <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-3">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex-1 min-w-0">
            <div className="text-xs text-slate-500">안건</div>
            <div className="text-base text-slate-100 font-semibold break-words">
              {session.agenda ?? '(미지정)'}
            </div>
          </div>
          <span
            className={`px-2 py-1 rounded border text-[11px] font-bold whitespace-nowrap ${outcomeBadgeClasses(
              final?.outcome,
            )}`}
          >
            {final?.outcome?.toUpperCase() ?? 'PENDING'}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-slate-400">
          <div>
            <span className="text-slate-500">session_id</span>{' '}
            <span className="font-mono text-slate-300">
              {session.session_id ?? '?'}
            </span>
          </div>
          <div>
            <span className="text-slate-500">schema</span>{' '}
            <span className="font-mono text-slate-300">
              {data.schema_version ?? '?'}
            </span>
          </div>
          <div>
            <span className="text-slate-500">opened</span>{' '}
            <span className="font-mono text-slate-300">
              {formatTimestamp(session.opened_at)}
            </span>
          </div>
          <div>
            <span className="text-slate-500">closed</span>{' '}
            <span className="font-mono text-slate-300">
              {formatTimestamp(session.closed_at)}
            </span>
          </div>
        </div>
        {session.attendees && session.attendees.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {session.attendees.map((a) => (
              <span
                key={a}
                className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300 font-mono"
              >
                {a}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* ============ Tikitaka Rounds (v2, PR #224) ============ */}
      {isV2 && rounds.length > 0 && (
        <SectionCard
          icon="💬"
          title="Tikitaka Rounds"
          subtitle={`본부 10 Cross-Agent Consultant — ${rounds.length} 라운드 진행`}
          statusBadge={
            <span className="px-2 py-0.5 rounded border text-[10px] font-bold bg-purple-900/40 text-purple-300 border-purple-700">
              v2
            </span>
          }
        >
          <div className="space-y-2.5">
            {rounds.map((r, i) => (
              <RoundCard key={r.round_num ?? i} round={r} />
            ))}
          </div>
        </SectionCard>
      )}

      {/* ⭐ Phase 5.E empty state — v2 yaml 인데 rounds=[] 인 경우 명시 안내 */}
      {isV2 && rounds.length === 0 && (
        <SectionCard
          icon="💬"
          title="Tikitaka Rounds"
          subtitle="본부 10 Cross-Agent Consultant"
          statusBadge={
            <span className="px-2 py-0.5 rounded border text-[10px] font-bold bg-slate-800 text-slate-400 border-slate-700">
              skipped
            </span>
          }
        >
          <div className="text-[11px] text-slate-400 leading-relaxed">
            이번 회의는 <span className="text-slate-300 font-mono">enable_tikitaka=False</span> 로 진행 — Phase 4 직렬 의결 모드 (alignment → budget 단방향).
            <br />
            <br />
            티키타카 활성 방법:{' '}
            <span className="text-slate-300 font-mono">--enable-tikitaka</span> flag (
            <span className="text-slate-300 font-mono">--enable-boardroom</span> 과 함께)
          </div>
        </SectionCard>
      )}

      {isV2 && consensus && (
        <SectionCard
          icon="🤝"
          title="Consensus"
          subtitle="Facilitator 종합 — 라운드 결과 타협안"
          statusBadge={null}
        >
          <div className="text-[12px] text-emerald-200 italic leading-relaxed">
            "{consensus}"
          </div>
        </SectionCard>
      )}

      {/* ============ Alignment 카드 ============ */}
      <SectionCard
        icon="🔵"
        title="Goal Alignment"
        subtitle="본부 0 — 시스템 목적 + 보안 거버넌스 조율"
        statusBadge={
          alignment ? (
            <span
              className={`px-2 py-0.5 rounded border text-[10px] font-bold ${statusBadgeClasses(
                alignment.status,
              )}`}
            >
              {alignment.status?.toUpperCase() ?? '?'}
            </span>
          ) : (
            <span className="text-[10px] text-slate-500">(not assessed)</span>
          )
        }
      >
        {alignment && (
          <>
            <div className="text-[12px] text-slate-300 mb-2">
              {alignment.reason ?? '(사유 없음)'}
            </div>
            {alignment.references && alignment.references.length > 0 && (
              <div className="text-[10px] text-slate-500">
                참조:{' '}
                {alignment.references.map((r, i) => (
                  <span key={i} className="font-mono text-slate-400 mr-2">
                    {r}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </SectionCard>

      {/* ============ Budget 카드 ============ */}
      <SectionCard
        icon="🟡"
        title="Token Budget"
        subtitle="본부 0 — LLM 비용 + 컴퓨팅 자원 한도 브레이크"
        statusBadge={
          budget ? (
            <span
              className={`px-2 py-0.5 rounded border text-[10px] font-bold ${statusBadgeClasses(
                budget.status,
              )}`}
            >
              {budget.status?.toUpperCase() ?? '?'}
            </span>
          ) : (
            <span className="text-[10px] text-slate-500">(not assessed)</span>
          )
        }
      >
        {budget && (
          <>
            <div className="text-[12px] text-slate-300 mb-2">
              {budget.reason ?? '(사유 없음)'}
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <BudgetMetric
                label="예상 비용"
                value={budget.estimated_cost_usd}
                accent="text-blue-300"
              />
              <BudgetMetric
                label="누적"
                value={budget.cumulative_cost_usd}
                accent="text-slate-300"
              />
              <BudgetMetric
                label="한도"
                value={budget.budget_limit_usd}
                accent="text-amber-300"
              />
            </div>
          </>
        )}
      </SectionCard>

      {/* ============ Final Decision 카드 ============ */}
      <SectionCard
        icon={final?.outcome === 'approved' ? '🟢' : '🔴'}
        title="Final Decision"
        subtitle="alignment + budget 종합 (OR 조건)"
        statusBadge={
          final ? (
            <span
              className={`px-2 py-0.5 rounded border text-[10px] font-bold ${outcomeBadgeClasses(
                final.outcome,
              )}`}
            >
              {final.outcome?.toUpperCase() ?? '?'}
            </span>
          ) : (
            <span className="text-[10px] text-slate-500">(pending)</span>
          )
        }
      >
        {final && (
          <>
            <div className="text-[12px] text-slate-300 mb-2">
              {final.reason ?? '(사유 없음)'}
            </div>
            {final.blocked_by && final.blocked_by.length > 0 && (
              <div className="text-[10px] text-red-300">
                blocked_by:{' '}
                {final.blocked_by.map((b, i) => (
                  <span
                    key={i}
                    className="font-mono text-red-200 mr-2 px-1.5 py-0.5 rounded bg-red-950/40"
                  >
                    {b}
                  </span>
                ))}
              </div>
            )}
            {final.decided_at && (
              <div className="text-[10px] text-slate-500 mt-1">
                결정 시각: {formatTimestamp(final.decided_at)}
              </div>
            )}
          </>
        )}
      </SectionCard>
    </div>
  )
}

interface SectionCardProps {
  icon: string
  title: string
  subtitle: string
  statusBadge: React.ReactNode | null
  children?: React.ReactNode
}

function SectionCard({
  icon,
  title,
  subtitle,
  statusBadge,
  children,
}: SectionCardProps) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg leading-none">{icon}</span>
          <div className="min-w-0">
            <div className="text-sm text-slate-100 font-semibold">{title}</div>
            <div className="text-[10px] text-slate-500 truncate">
              {subtitle}
            </div>
          </div>
        </div>
        {statusBadge}
      </div>
      {children}
    </div>
  )
}

function roleBadgeClasses(role?: string): string {
  switch (role) {
    case 'proposer':
      return 'bg-sky-900/40 text-sky-300 border-sky-700'
    case 'reviewer':
      return 'bg-slate-800 text-slate-300 border-slate-600'
    case 'dissenter':
      return 'bg-red-900/40 text-red-300 border-red-700'
    case 'mediator':
      return 'bg-emerald-900/40 text-emerald-300 border-emerald-700'
    default:
      return 'bg-slate-800 text-slate-400 border-slate-700'
  }
}

interface RoundCardProps {
  round: RoundSection
}

function RoundCard({ round }: RoundCardProps) {
  const statements = round.statements ?? []
  const dissent = Boolean(round.dissent_detected)
  return (
    <div
      className={`rounded border p-2 ${
        dissent
          ? 'border-red-700/60 bg-red-950/15'
          : 'border-slate-700 bg-slate-900/40'
      }`}
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-xs font-bold text-slate-200">
          Round {round.round_num ?? '?'}
        </div>
        <span
          className={`text-[9px] px-1.5 py-0.5 rounded border ${
            dissent
              ? 'bg-red-900/40 text-red-300 border-red-700'
              : 'bg-emerald-900/40 text-emerald-300 border-emerald-700'
          }`}
        >
          {dissent ? 'dissent ⚠' : 'consensus ✓'}
        </span>
      </div>
      {statements.length === 0 ? (
        <div className="text-[10px] text-slate-500 italic px-1">
          (라운드 발언 미수집 — budget throttle 또는 LLM 호출 실패 가능)
        </div>
      ) : (
        <ul className="space-y-1">
          {statements.map((s, i) => (
            <li
              key={i}
              className="flex items-start gap-1.5 text-[11px] leading-snug"
            >
              <span
                className={`flex-shrink-0 px-1 py-0 rounded border text-[9px] font-mono ${roleBadgeClasses(s.role)}`}
                title={s.role ?? '?'}
              >
                {s.role?.[0]?.toUpperCase() ?? '?'}
              </span>
              <span className="flex-1 min-w-0">
                <span className="font-mono text-slate-400 text-[10px]">
                  {s.agent ?? '?'}:
                </span>{' '}
                <span className="text-slate-200">{s.content ?? '(빈 발언)'}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface BudgetMetricProps {
  label: string
  value?: number | null
  accent: string
}

function BudgetMetric({ label, value, accent }: BudgetMetricProps) {
  const formatted =
    value === null || value === undefined ? '—' : `$${value.toFixed(2)}`
  return (
    <div className="rounded bg-slate-800/60 border border-slate-700 px-2 py-1.5">
      <div className="text-[9px] text-slate-500 uppercase tracking-wide">
        {label}
      </div>
      <div className={`text-sm font-mono font-bold ${accent}`}>{formatted}</div>
    </div>
  )
}
