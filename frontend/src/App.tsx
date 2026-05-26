import { useState } from 'react'

/**
 * Sprint 5 PR-B — Agent Office Visualizer 의 *최소 부서 그리드 placeholder*.
 *
 * 본 컴포넌트는 docs/insights/desktop_app_vision.md §2 의 부서별 색상 매핑을
 * 데이터 차원으로 그대로 가져와 *정적 placeholder* 로 렌더한다.
 *
 * PR-C 가 도착하면:
 *   - 자연어 입력창이 Tauri command (`start_run`) 를 invoke 한다.
 *   - Python sidecar 가 emit 한 events.jsonl 의 4 event type 이
 *     working/done 상태를 카드별 펄스로 갱신한다.
 *
 * 본 PR 시점에는 카드를 클릭하면 active 상태만 토글된다.
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

function App() {
  const [request, setRequest] = useState('')
  const [activeDept, setActiveDept] = useState<DeptKey | null>(null)

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 to-slate-900 text-slate-100 p-8">
      <header className="mb-8 max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold text-sky-400 mb-1">
          Nexus Alpha — Agent Office
        </h1>
        <p className="text-slate-400 text-sm">
          Sprint 5 PR-B — React + Tailwind 부서 그리드 placeholder. PR-C 에서 Python
          sidecar 와 wire 됩니다.
        </p>
      </header>

      <section className="mb-8 max-w-6xl mx-auto">
        <label className="block text-slate-300 mb-2 text-sm font-semibold">
          자연어 요청 <span className="text-slate-500 font-normal">(PR-C 에서 Tauri command 로 wire)</span>
        </label>
        <input
          type="text"
          className="w-full px-4 py-3 bg-slate-800/80 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 transition"
          placeholder="예: 네이버 쇼핑 크롤러 만들어줘"
          value={request}
          onChange={(e) => setRequest(e.target.value)}
        />
      </section>

      <section className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-6xl mx-auto">
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

      <footer className="mt-8 p-4 border border-dashed border-slate-700 rounded-lg text-sm text-slate-400 max-w-6xl mx-auto">
        <strong className="text-slate-300">PR-C 도착 후:</strong> 본 그리드의 부서 펄스
        ON/OFF, 부서 강조, working agent 가 <code className="px-1 bg-slate-800 rounded text-slate-300">events.jsonl</code> 의
        AgentStatusEvent 에 따라 실시간 갱신됩니다.
      </footer>
    </div>
  )
}

export default App
