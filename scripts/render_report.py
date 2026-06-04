# -*- coding: utf-8 -*-
"""v13 P21 — 결합 마크다운 → HTML / PDF 렌더 (markdown → HTML → Playwright print).

`docs/ARCHITECTURE_OVERVIEW` 생성에 쓴 것과 *동일* 파이프라인을 공통 모듈로 정착시킨 것:
python-markdown(표/펜스/mermaid) → 스타일 HTML → (PDF 면) Playwright headless Chromium
`page.pdf()`. mermaid 코드블록은 `<pre class="mermaid">` 로 변환 후 mermaid.js(CDN)로 렌더하며,
CDN 미도달(오프라인)이어도 소스가 텍스트로 보여 산출은 정상 생성된다(graceful).

순수 렌더러 — *입력 마크다운 파일만* 읽는다(런 산출물 디렉터리는 건드리지 않음; 호출자(Rust)가
경로 제한 하에 결합 마크다운을 만들어 넘긴다). 쓰기는 `--out` 한 파일뿐.

사용:
    python render_report.py --mode {html,pdf} --in <combined.md> --out <path.{html,pdf}> [--title T]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import markdown as md

_CSS = """
  * { box-sizing: border-box; }
  body { font-family: 'Malgun Gothic','Segoe UI',sans-serif; color:#1f2937; line-height:1.55;
         font-size:11px; margin:0; padding:0 8px; }
  h1 { font-size:21px; color:#0f172a; border-bottom:3px solid #2563eb; padding-bottom:6px; margin-top:6px; }
  h2 { font-size:15.5px; color:#1e3a8a; border-bottom:1px solid #cbd5e1; padding-bottom:3px; margin-top:18px; page-break-after:avoid; }
  h3 { font-size:13px; color:#1e40af; margin-top:12px; page-break-after:avoid; }
  table { border-collapse:collapse; width:100%; margin:8px 0; font-size:10px; page-break-inside:avoid; }
  th,td { border:1px solid #cbd5e1; padding:5px 7px; text-align:left; vertical-align:top; }
  th { background:#eff6ff; color:#1e3a8a; font-weight:700; }
  tr:nth-child(even) td { background:#f8fafc; }
  code { background:#f1f5f9; padding:1px 4px; border-radius:3px; font-family:'Consolas',monospace; font-size:9.5px; color:#0f172a; }
  pre { background:#0f172a; color:#e2e8f0; padding:9px 11px; border-radius:6px; overflow:auto; font-size:9px; line-height:1.4; page-break-inside:avoid; }
  pre code { background:transparent; color:inherit; padding:0; }
  pre.mermaid { background:#ffffff; color:#0f172a; border:1px solid #e2e8f0; text-align:center; }
  blockquote { border-left:4px solid #f59e0b; background:#fffbeb; margin:8px 0; padding:6px 12px; color:#78350f; border-radius:0 4px 4px 0; }
  hr { border:none; border-top:1px solid #e2e8f0; margin:14px 0; }
  a { color:#2563eb; text-decoration:none; } strong { color:#0f172a; } em { color:#475569; }
"""

_HTML_TMPL = (
    '<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>__TITLE__</title>'
    "<style>__CSS__</style>"
    '<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>'
    "<script>window.__mmReady=false;try{mermaid.initialize({startOnLoad:false,theme:'default',"
    "flowchart:{htmlLabels:true}});window.addEventListener('load',async()=>{try{await "
    "mermaid.run({querySelector:'pre.mermaid'});}catch(e){}window.__mmReady=true;});}"
    "catch(e){window.__mmReady=true;}</script></head><body>__BODY__</body></html>"
)


def md_to_html_doc(md_text: str, title: str = "Report") -> str:
    """결합 마크다운 → 단일 HTML 문서 문자열 (mermaid 블록은 pre.mermaid 로 보존)."""
    stash: list[str] = []

    def _grab(m: "re.Match[str]") -> str:
        stash.append(m.group(1))
        return f"\n\nMERMTOK{len(stash) - 1}MERMTOK\n\n"

    pre = re.sub(r"```mermaid\n(.*?)```", _grab, md_text, flags=re.DOTALL)
    body = md.markdown(pre, extensions=["tables", "fenced_code", "sane_lists"])

    def _restore(m: "re.Match[str]") -> str:
        return f'<pre class="mermaid">{stash[int(m.group(1))]}</pre>'

    body = re.sub(r"<p>MERMTOK(\d+)MERMTOK</p>", _restore, body)
    body = re.sub(r"MERMTOK(\d+)MERMTOK", _restore, body)
    return (
        _HTML_TMPL.replace("__TITLE__", title).replace("__CSS__", _CSS).replace("__BODY__", body)
    )


def html_to_pdf(html: str, out_path: Path) -> None:
    """HTML → PDF (Playwright headless Chromium print). mermaid 렌더 대기 후 page.pdf()."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            try:
                page.wait_for_function("window.__mmReady === true", timeout=12000)
            except Exception:  # noqa: BLE001 — CDN 미도달 시 타임아웃 후 진행(소스 텍스트로 degrade)
                pass
            page.wait_for_timeout(700)
            page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
            )
        finally:
            browser.close()


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="결합 마크다운 → HTML/PDF 렌더 (P21)")
    ap.add_argument("--mode", choices=["html", "pdf"], required=True)
    ap.add_argument("--in", dest="inp", required=True, help="결합 마크다운 파일 경로")
    ap.add_argument("--out", dest="out", required=True, help="출력 경로(.html/.pdf)")
    ap.add_argument("--title", default="Run Report")
    args = ap.parse_args(argv)

    md_text = Path(args.inp).read_text(encoding="utf-8")
    html = md_to_html_doc(md_text, title=args.title)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "html":
        out.write_text(html, encoding="utf-8")
    else:
        html_to_pdf(html, out)
    size = out.stat().st_size if out.exists() else 0
    print(f"render_report: {args.mode} -> {out} ({size} bytes)")
    return 0 if size > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
