// =============================================================================
// RunReportPanel — v13 P21 (런 리포트, 읽기 전용)
// =============================================================================
//
// outputs/alpha_run_* 의 workflow_* 단계 파일들을 *본부별로* 묶어 렌더하고, 한 번에
// PDF/HTML/zip 으로 내보내는 읽기 전용 뷰. LLM 호출 0 — 전부 파일 파싱.
//
//   ┌────────────────────┬──────────────────────────────────────────┐
//   │ 런 선택 + 본부 트리 │  메타 개요 + 다운로드 3종 + 파일 렌더     │
//   │ (사이드바)         │  (.md 마크다운 / .txt pre / .yaml·.json) │
//   └────────────────────┴──────────────────────────────────────────┘
//
// Tauri commands (읽기/내보내기 전용, outputs/ 경로 제한):
//   list_runs / get_run_report / read_run_file / export_run_report / open_report_folder

import { useCallback, useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface RunSummary {
  run_id: string
  timestamp: string
  request: string
  stage_count: number
  verdict: string
  iterations: string
}
interface StageFile {
  filename: string
  rel_path: string
  hq_key: string
  hq_label: string
  order: number
  label: string
  kind: string
}
interface CodeEntry {
  rel_path: string
  kind: string
}
interface RunReport {
  run_id: string
  timestamp: string
  request: string
  verdict: string
  iterations: string
  workflow_dir: string
  stages: StageFile[]
  code_files: CodeEntry[]
}
interface FileContent {
  kind: string
  truncated: boolean
  content: string
}

function fmtTs(iso?: string): string {
  if (!iso) return '?'
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso
}

function verdictClass(v?: string): string {
  if (v === 'COMPLETE') return 'bg-emerald-900/40 text-emerald-300 border-emerald-700'
  if (v === 'BLOCKED') return 'bg-red-900/40 text-red-300 border-red-700'
  if (v === 'IMPROVE_NEEDED') return 'bg-amber-900/40 text-amber-300 border-amber-700'
  return 'bg-slate-800 text-slate-400 border-slate-700'
}

export function RunReportPanel() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [report, setReport] = useState<RunReport | null>(null)
  const [selFile, setSelFile] = useState<{ rel_path: string; filename: string; kind: string } | null>(null)
  const [fileContent, setFileContent] = useState<FileContent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [exportMsg, setExportMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const loadRuns = useCallback(async () => {
    try {
      const list = await invoke<RunSummary[]>('list_runs')
      setRuns(list)
      setError(null)
      setSelectedRun((prev) => prev ?? (list.length > 0 ? list[0].run_id : null))
    } catch (e) {
      setError(`런 목록 로드 실패: ${String(e)}`)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadRuns()
  }, [loadRuns])

  // 런 선택 → 리포트 로드
  useEffect(() => {
    if (!selectedRun) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setReport(null)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const r = await invoke<RunReport>('get_run_report', { runId: selectedRun })
        if (!cancelled) {
          setReport(r)
          setSelFile(null)
          setFileContent(null)
          setExportMsg(null)
          setError(null) // 성공 시 직전 에러 클리어
        }
      } catch (e) {
        if (!cancelled) {
          setReport(null)
          setError(`리포트 로드 실패: ${String(e)}`)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedRun])

  // 파일 선택 → 내용 로드
  useEffect(() => {
    if (!selectedRun || !selFile) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setFileContent(null)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const c = await invoke<FileContent>('read_run_file', {
          runId: selectedRun,
          relPath: selFile.rel_path,
        })
        if (!cancelled) setFileContent(c)
      } catch (e) {
        if (!cancelled)
          setFileContent({ kind: 'other', truncated: false, content: `읽기 실패: ${String(e)}` })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedRun, selFile])

  const groups = useMemo(() => {
    if (!report) return [] as { label: string; files: StageFile[]; minOrder: number }[]
    const m = new Map<string, { label: string; files: StageFile[]; minOrder: number }>()
    for (const s of report.stages) {
      if (!m.has(s.hq_label)) m.set(s.hq_label, { label: s.hq_label, files: [], minOrder: s.order })
      const g = m.get(s.hq_label)!
      g.files.push(s)
      g.minOrder = Math.min(g.minOrder, s.order)
    }
    // 본부 그룹을 대표(최소) order 로 정렬 — 비연속 order(04·14 둘 다 QA)에서도 파이프라인 순서 유지.
    return Array.from(m.values()).sort((a, b) => a.minOrder - b.minOrder)
  }, [report])

  const doExport = async (format: 'pdf' | 'html' | 'zip') => {
    if (!selectedRun || busy) return
    setBusy(true)
    setExportMsg(`${format.toUpperCase()} 생성 중…`)
    try {
      const path = await invoke<string>('export_run_report', { runId: selectedRun, format })
      setExportMsg(`✅ ${format.toUpperCase()} 저장됨 — ${path}`)
    } catch (e) {
      setExportMsg(`⚠ ${format.toUpperCase()} 실패: ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const openFolder = async () => {
    if (!selectedRun) return
    try {
      await invoke('open_report_folder', { runId: selectedRun })
    } catch (e) {
      setExportMsg(`폴더 열기 실패: ${String(e)}`)
    }
  }

  const curRunMeta = runs.find((r) => r.run_id === selectedRun)

  return (
    <div className="flex h-full min-h-0 bg-[#0d1117] text-slate-200">
      {/* === Left: 런 선택 + 본부 트리 === */}
      <aside className="w-[260px] flex-shrink-0 border-r border-slate-800 flex flex-col">
        <div className="px-3 py-2 border-b border-slate-800">
          <div className="flex items-center justify-between mb-1.5">
            <div className="text-xs font-bold text-sky-300">런 리포트</div>
            <button
              type="button"
              onClick={() => void loadRuns()}
              className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
              title="런 목록 새로고침"
            >
              ↻
            </button>
          </div>
          {runs.length === 0 ? (
            <div className="text-[10px] text-slate-500">
              {error ?? 'outputs/alpha_run_* 런이 없습니다.'}
            </div>
          ) : (
            <select
              value={selectedRun ?? ''}
              onChange={(e) => setSelectedRun(e.target.value)}
              className="w-full px-1.5 py-1 bg-slate-900 border border-slate-700 rounded text-[10px] text-slate-100 focus:outline-none focus:border-sky-500"
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id.replace('alpha_run_', '')} · {r.stage_count}단계
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="flex-1 overflow-y-auto py-1">
          {!report ? (
            <div className="p-3 text-[11px] text-slate-500">
              {selectedRun ? '리포트 로딩 중…' : '런을 선택하세요.'}
            </div>
          ) : (
            <>
              {groups.map((g) => (
                <div key={g.label} className="mb-1">
                  <div className="px-3 py-1 text-[9px] font-bold uppercase tracking-wide text-slate-400 bg-slate-900/40">
                    {g.label}
                  </div>
                  <ul>
                    {g.files.map((f) => {
                      const isSel = selFile?.rel_path === f.rel_path
                      return (
                        <li key={f.rel_path}>
                          <button
                            type="button"
                            onClick={() => setSelFile(f)}
                            className={`w-full text-left px-3 py-1 text-[10px] border-l-2 transition ${
                              isSel
                                ? 'border-sky-500 bg-sky-500/10 text-sky-200'
                                : 'border-transparent text-slate-300 hover:bg-slate-800/50'
                            }`}
                            title={f.label}
                          >
                            <div className="font-mono text-slate-300 truncate">{f.filename}</div>
                            {f.label && (
                              <div className="text-[9px] text-slate-500 truncate">{f.label}</div>
                            )}
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              ))}
              {report.code_files.length > 0 && (
                <div className="mb-1">
                  <div className="px-3 py-1 text-[9px] font-bold uppercase tracking-wide text-slate-400 bg-slate-900/40">
                    code/ ({report.code_files.length})
                  </div>
                  <ul>
                    {report.code_files.map((c) => {
                      const rel = `${report.workflow_dir}/code/${c.rel_path}`
                      const isSel = selFile?.rel_path === rel
                      return (
                        <li key={c.rel_path}>
                          <button
                            type="button"
                            onClick={() =>
                              setSelFile({ rel_path: rel, filename: c.rel_path, kind: c.kind })
                            }
                            className={`w-full text-left px-3 py-0.5 text-[10px] font-mono border-l-2 transition truncate ${
                              isSel
                                ? 'border-sky-500 bg-sky-500/10 text-sky-200'
                                : 'border-transparent text-slate-400 hover:bg-slate-800/50'
                            }`}
                            title={c.rel_path}
                          >
                            {c.rel_path}
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </aside>

      {/* === Center: 메타 개요 + 다운로드 + 파일 렌더 === */}
      <main className="flex-1 min-w-0 flex flex-col">
        {/* 메타 개요 */}
        {report && (
          <div className="flex-shrink-0 border-b border-slate-800 px-4 py-2.5 bg-[#161b22]">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono text-xs text-slate-100">{report.run_id}</span>
                  <span className="text-[9px] text-slate-500">{fmtTs(curRunMeta?.timestamp)}</span>
                  <span
                    className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${verdictClass(report.verdict)}`}
                    title="events.jsonl 의 ResultEvent 기준 (없으면 미상)"
                  >
                    {report.verdict}
                  </span>
                  <span className="text-[9px] text-slate-500">iter {report.iterations}</span>
                  <span className="text-[9px] text-slate-500">· {report.stages.length}단계</span>
                </div>
                <div className="text-[11px] text-slate-300 line-clamp-2" title={report.request}>
                  {report.request || '(요청 없음)'}
                </div>
              </div>
              <div className="flex-shrink-0 flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => void doExport('pdf')}
                  disabled={busy}
                  className="px-2 py-1 text-[10px] rounded bg-rose-700/70 hover:bg-rose-600 disabled:opacity-50 text-white"
                  title="본부별 정렬 리포트를 PDF 로 (markdown→HTML→Playwright)"
                >
                  PDF
                </button>
                <button
                  type="button"
                  onClick={() => void doExport('html')}
                  disabled={busy}
                  className="px-2 py-1 text-[10px] rounded bg-sky-700/70 hover:bg-sky-600 disabled:opacity-50 text-white"
                  title="단일 HTML 파일"
                >
                  HTML
                </button>
                <button
                  type="button"
                  onClick={() => void doExport('zip')}
                  disabled={busy}
                  className="px-2 py-1 text-[10px] rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-white"
                  title="원본 단계 파일 zip 묶음"
                >
                  ZIP
                </button>
              </div>
            </div>
            {exportMsg && (
              <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px]">
                <span className="text-slate-400 break-all">{exportMsg}</span>
                <button
                  type="button"
                  onClick={() => void openFolder()}
                  className="flex-shrink-0 px-1.5 py-0.5 rounded border border-slate-600 hover:border-slate-400 text-slate-300"
                >
                  폴더 열기
                </button>
              </div>
            )}
          </div>
        )}

        {/* 파일 렌더 */}
        <div className="flex-1 min-h-0 overflow-y-auto p-4">
          {!report ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm">
              {error ?? '왼쪽에서 런과 단계 파일을 선택하세요.'}
            </div>
          ) : !selFile ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm text-center px-6">
              왼쪽 본부별 트리에서 단계 파일을 클릭하면 여기에 렌더됩니다.
              <br />
              상단 PDF / HTML / ZIP 으로 전체 리포트를 내려받을 수 있습니다.
            </div>
          ) : !fileContent ? (
            <div className="text-slate-500 text-sm">로딩 중…</div>
          ) : (
            <div>
              <div className="text-[11px] text-slate-500 mb-2 font-mono">
                {selFile.rel_path}
                {fileContent.truncated && (
                  <span className="ml-2 text-amber-400">(일부만 표시 — 거대 파일)</span>
                )}
              </div>
              {selFile.kind === 'md' ? (
                <div className="report-md">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{fileContent.content}</ReactMarkdown>
                </div>
              ) : (
                <pre className="text-[11px] text-slate-200 whitespace-pre-wrap break-words font-mono bg-slate-950/60 rounded p-3 leading-relaxed">
                  {fileContent.content}
                </pre>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
