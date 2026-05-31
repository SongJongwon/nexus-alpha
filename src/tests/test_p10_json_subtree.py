# -*- coding: utf-8 -*-
"""P10 jsonc 추출 + src/ 서브트리 + manifest 보장 회귀 test (v13 Phase 6.E).

출처: ``docs/diagnostics/phase6e_rerun_P9_verdict_20260531.md`` (두 벽 규명).

벽1 = package.json/tsconfig 를 ```jsonc 로 fence → jsonc ∉ _WEB_CODE_LANGS → 언어 게이트
       (:247 `if lang not in allowed: continue`)가 _resolve_block_filename 이전 → 드롭.
벽2 = 평탄화(src/main.ts→src__main.ts) + un-flatten 전무 → index.html `/src/main.ts` 가
       평탄 파일과 불일치 → vite/tsc import 해소 실패.

처방:
    P10a(1) jsonc/json5 를 _WEB_CODE_LANGS + _FENCE_LANG_EXT(→.json) 추가 + well-known 가드 확장.
    P10a(2) jsonc→strict JSON 정규화(// 줄·/* */·trailing comma 제거, 문자열 보존).
    P10b(i) web 경로(preserve_tree) 실 src/ 서브트리 작성 + build_workflow code_dir=workflow_dir/code.
    P10a(3) salvage(미상장 fence)→synthesize(import 추론) manifest 보장 (fail-loud).

검증: P10-T1~T13 (verdict 표대로). 회귀 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows.analyze_and_implement import (
    _WEB_CODE_LANGS,
    _ensure_web_manifests,
    _extract_code_blocks,
    _find_manifest_block,
    _normalize_jsonc_to_json,
    _safe_rel_path,
    _synthesize_package_json,
)
from src.workflows.build_workflow import _run_web_build


# =============================================================================
# P10-T1. jsonc 허용 + 정규화 + 헤더제거 → 유효 package.json
# =============================================================================
class TestT1JsoncAllowedValid:
    _MD = (
        "```jsonc\n"
        "// file: package.json\n"
        '{\n  "name": "demo",  // 앱 이름\n'
        '  "dependencies": {"three": "^0.160.0"},\n}\n'  # 인라인 주석 + trailing comma
        "```\n"
    )

    def test_jsonc_extracted_and_valid(self, tmp_path: Path) -> None:
        saved = {p.name: p for p in _extract_code_blocks(self._MD, tmp_path, languages=_WEB_CODE_LANGS)}
        assert "package.json" in saved
        data = json.loads(saved["package.json"].read_text(encoding="utf-8"))  # //·trailing comma 제거 후 valid
        assert data["name"] == "demo"
        assert data["dependencies"]["three"] == "^0.160.0"


# =============================================================================
# P10-T2. json5 fence → .json
# =============================================================================
class TestT2Json5Fence:
    _MD = "```json5\n// file: package.json\n" '{"name": "x", "dependencies": {}}\n' "```\n"

    def test_json5_extracted(self, tmp_path: Path) -> None:
        saved = {p.name for p in _extract_code_blocks(self._MD, tmp_path, languages=_WEB_CODE_LANGS)}
        assert "package.json" in saved


# =============================================================================
# P10-T3. jsonc→strict 정규화 (주석/trailing comma 제거)
# =============================================================================
class TestT3NormalizeComments:
    def test_strips_comments_and_trailing_commas(self) -> None:
        src = '{\n  "a": 1, // line\n  /* block */ "b": [1, 2,],\n}'
        assert json.loads(_normalize_jsonc_to_json(src)) == {"a": 1, "b": [1, 2]}


# =============================================================================
# P10-T4. 정규화가 문자열 내부 //·, 보존 (단독 정규식의 corruption 방지)
# =============================================================================
class TestT4NormalizePreservesStrings:
    def test_string_slashes_and_commas_preserved(self) -> None:
        src = '{"url": "http://x.com/a", "csv": "a,]", "c": "/* not comment */"}'
        out = _normalize_jsonc_to_json(src)
        assert json.loads(out) == {"url": "http://x.com/a", "csv": "a,]", "c": "/* not comment */"}


# =============================================================================
# P10-T5. preserve_tree → 실 src/ 서브트리 (index.html /src/main.ts 와 일치)
# =============================================================================
class TestT5PreserveTreeSubtree:
    _MD = (
        "```ts\n// file: src/ui/toolbar.ts\nexport const x = 1;\n```\n"
        "```ts\n// file: src/main.ts\nimport './ui/toolbar';\n```\n"
        "```html\n<!-- file: index.html -->\n"
        '<script type="module" src="/src/main.ts"></script>\n```\n'
    )

    def test_real_subtree_written(self, tmp_path: Path) -> None:
        _extract_code_blocks(self._MD, tmp_path, languages=_WEB_CODE_LANGS, preserve_tree=True)
        # index.html 의 /src/main.ts ↔ 실제 파일 일치 (vite 네이티브 해소)
        assert (tmp_path / "src" / "main.ts").is_file()
        assert (tmp_path / "src" / "ui" / "toolbar.ts").is_file()
        assert (tmp_path / "src").is_dir()
        assert (tmp_path / "index.html").is_file()
        # 평탄화 안 됨
        assert not (tmp_path / "src__main.ts").exists()
        assert not (tmp_path / "src__ui__toolbar.ts").exists()


# =============================================================================
# P10-T6. preserve_tree=False(기본) → 평탄 유지 (Track A/non-web 불변)
# =============================================================================
class TestT6DefaultFlat:
    def test_default_flattens(self, tmp_path: Path) -> None:
        md = "```ts\n// file: src/main.ts\nconst x = 1;\n```\n"
        _extract_code_blocks(md, tmp_path, languages=_WEB_CODE_LANGS)  # preserve_tree=False 기본
        assert (tmp_path / "src__main.ts").is_file()
        assert not (tmp_path / "src").exists()


# =============================================================================
# P10-T7. _safe_rel_path traversal 가드
# =============================================================================
class TestT7SafeRelPath:
    def test_normal_relative(self) -> None:
        assert _safe_rel_path("src/ui/toolbar.ts") == Path("src/ui/toolbar.ts")
        assert _safe_rel_path("src\\main.ts") == Path("src/main.ts")

    def test_traversal_rejected(self) -> None:
        assert _safe_rel_path("../escape.ts") is None
        assert _safe_rel_path("a/../../b.ts") is None
        assert _safe_rel_path("C:/abs.ts") is None

    def test_leading_slash_contained(self) -> None:
        # 선두 / 는 제거되어 code_dir 내부로 contained (escape 아님)
        assert _safe_rel_path("/src/main.ts") == Path("src/main.ts")


# =============================================================================
# P10-T8. _run_web_build code_dir = workflow_dir/"code" (서브트리에도 정확)
# =============================================================================
class TestT8WebBuildCodeDir:
    def test_code_dir_anchored_to_workflow_code(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        (code_dir / "src").mkdir(parents=True)
        captured = {}

        def fake(cd: Path, timeout: int):
            captured["cd"] = cd
            return False, "stub", 0.0

        # 첫 code_file 이 서브트리(code/src/main.ts) — 기존 code_files[0].parent 면 code/src 오류
        _run_web_build(
            [code_dir / "src" / "main.ts", code_dir / "package.json"],
            tmp_path,
            npm_runner=fake,
        )
        assert captured["cd"] == code_dir  # NOT code/src

    def test_existing_flat_layout_unchanged(self, tmp_path: Path) -> None:
        # 기존 P7 테스트 패턴 — 평탄 layout 도 동일하게 code_dir=tmp_path/"code"
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        captured = {}

        def fake(cd: Path, timeout: int):
            captured["cd"] = cd
            return False, "stub", 0.0

        _run_web_build([code_dir / "vite.config.ts"], tmp_path, npm_runner=fake)
        assert captured["cd"] == code_dir


# =============================================================================
# P10-T9. python-only(Track A)/desktop 경로 불변 — 평탄 + 헤더 보존
# =============================================================================
class TestT9PythonDesktopUnchanged:
    def test_python_default_flat_header_preserved(self, tmp_path: Path) -> None:
        md = "```python\n# file: app.py\nprint(1)\n```\n"
        saved = {p.name: p for p in _extract_code_blocks(md, tmp_path)}  # _PY_ONLY_LANGS 기본
        assert set(saved) == {"app.py"}
        # 비-json 은 file: 헤더 줄 보존 (회귀 0)
        assert saved["app.py"].read_text(encoding="utf-8").startswith("# file: app.py")

    def test_desktop_pyqt_subtree_flat_when_no_slash(self, tmp_path: Path) -> None:
        # GUI 경로(preserve_tree=True)라도 "/" 없는 이름은 평탄 그대로 (데스크탑 드리프트 안전)
        md = "```python\n# file: main_window.py\nfrom PyQt6.QtWidgets import QApplication\n```\n"
        saved = {p.name for p in _extract_code_blocks(md, tmp_path, languages=_WEB_CODE_LANGS, preserve_tree=True)}
        assert "main_window.py" in saved
        assert (tmp_path / "main_window.py").is_file()


# =============================================================================
# P10-T10. salvage — 미상장 fence 의 manifest 복구
# =============================================================================
class TestT10SalvageUnlistedFence:
    def test_salvage_from_text_fence(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "main.ts").write_text("import * as THREE from 'three';", encoding="utf-8")
        code_paths = [code_dir / "main.ts"]
        # package.json 이 비-허용 fence(text)에 선언 → _extract 는 못 건지지만 salvage 가 복구
        gui = (
            "```text\n// file: package.json\n"
            '{\n  "name": "salv", // c\n  "dependencies": {"three": "^0.1.0"},\n}\n'
            "```\n"
        )
        added = _ensure_web_manifests(gui, code_dir, code_paths)
        assert (code_dir / "package.json") in added
        data = json.loads((code_dir / "package.json").read_text(encoding="utf-8"))
        assert data["name"] == "salv"

    def test_find_manifest_block_helper(self) -> None:
        gui = "```text\n// file: tsconfig.json\n{}\n```\n"
        body = _find_manifest_block(gui, "tsconfig.json")
        assert body is not None and body.strip() == "{}"


# =============================================================================
# P10-T11. synthesize — manifest 전무 시 import 추론 최소본 (fail-loud)
# =============================================================================
class TestT11Synthesize:
    def test_synthesize_minimal_package_json(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        (code_dir / "src").mkdir(parents=True)
        (code_dir / "src" / "main.ts").write_text(
            "import * as THREE from 'three';\n"
            "import { IFCLoader } from 'web-ifc-three/IFCLoader';\n"
            "import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';\n"
            "import './local';\n",
            encoding="utf-8",
        )
        code_paths = [code_dir / "src" / "main.ts"]
        gui = "```ts\n// file: src/main.ts\nimport * as THREE from 'three';\n```\n"  # package.json 블록 없음
        added = _ensure_web_manifests(gui, code_dir, code_paths)
        pkg = code_dir / "package.json"
        assert pkg in added and pkg.is_file()
        data = json.loads(pkg.read_text(encoding="utf-8"))
        assert "three" in data["dependencies"]  # bare import 추론
        assert "web-ifc-three" in data["dependencies"]  # subpath → 최상위 패키지명
        assert "./local" not in data["dependencies"]  # 상대 import 제외
        assert data["scripts"]["build"] == "tsc && vite build"
        # fail-loud 아티팩트
        assert (tmp_path / "13c_manifest_recovery.txt").is_file()

    def test_synthesize_helper_excludes_relative(self) -> None:
        # _synthesize_package_json 직접: 상대 import 제외, scoped 패키지 보존
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.ts"
            f.write_text("import x from '@scope/pkg';\nimport './rel';\n", encoding="utf-8")
            out = json.loads(_synthesize_package_json([f]))
            assert "@scope/pkg" in out["dependencies"]
            assert "./rel" not in out["dependencies"]


# =============================================================================
# P10-T12. _ensure_web_manifests no-op for 비-web (데스크탑)
# =============================================================================
class TestT12EnsureNoopDesktop:
    def test_noop_when_only_py(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        code_paths = [code_dir / "app.py", code_dir / "theme.py"]
        gui = "```python\n# file: app.py\nprint(1)\n```\n"
        assert _ensure_web_manifests(gui, code_dir, code_paths) == []
        assert not (code_dir / "package.json").exists()
        assert not (tmp_path / "13c_manifest_recovery.txt").exists()


# =============================================================================
# P10-T13. .ts/.html/.css + strict json(lang=json) 기존 동작 회귀 0
# =============================================================================
class TestT13WebFilesRegression:
    _MD = (
        "```ts\n// file: app.ts\nconst x = 1;\n```\n"
        "```html\n<!-- file: index.html -->\n<html></html>\n```\n"
        "```css\n/* file: styles.css */\nbody { color: red; }\n```\n"
        "```json\n// file: tsconfig.json\n" '{"compilerOptions": {"strict": true}}\n' "```\n"
    )

    def test_web_files_extract_and_headers(self, tmp_path: Path) -> None:
        saved = {p.name: p for p in _extract_code_blocks(self._MD, tmp_path, languages=_WEB_CODE_LANGS)}
        assert set(saved) == {"app.ts", "index.html", "styles.css", "tsconfig.json"}
        # 비-json 헤더 보존
        assert saved["app.ts"].read_text(encoding="utf-8").startswith("// file: app.ts")
        assert saved["index.html"].read_text(encoding="utf-8").startswith("<!-- file: index.html -->")
        # strict json(lang=json)도 헤더제거+정규화 후 유효 (P9 동작 불변)
        assert json.loads(saved["tsconfig.json"].read_text(encoding="utf-8")) == {
            "compilerOptions": {"strict": True}
        }
