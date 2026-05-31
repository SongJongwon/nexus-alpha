# -*- coding: utf-8 -*-
"""P9 json 추출 결함 회귀 test (v13 Phase 6.E).

출처: ``docs/diagnostics/phase6e_rerun_P3_verdict_20260531.md`` (벽 이동 → web build).

원인 확정 (P3 verdict, 시뮬레이션):
    LLM 이 13_gui_code_output.md 에 ``// file: package.json`` 헤더 + 완전한 package.json/
    tsconfig.json 을 emit 했으나 ``_extract_code_blocks`` 가 code/ 로 안 저장 = 추출 결함.
    진범 = 들여쓰기된 ```bash 의존성 블록의 닫는 fence(`  ``` `)가 column-0 앵커
    ``\\n``` `` 와 불일치 → 못 닫고 뒤를 삼킴 → 직후 두 ```json 블록 페어링 desync → 드롭.
    (헤더 가설 기각: ``//`` 헤더는 정상이고 정규식도 ``//`` 지원.)
    추가: 추출돼도 ``// file:`` 헤더 줄이 본문에 남아 JSON 무효 → npm 파싱 실패.

처방:
    P9-1. 닫는 fence 들여쓰기 허용(`\\n[ \\t]*```) → 페어링 복원.
    P9-2. fence-info 파일명(```json package.json) + 앞줄 "name:" + well-known(내용) 인식.
    P9-3. json 산출은 file: 헤더 줄 제거 → 유효 JSON 보장.
    P9-4. _detect_extraction_loss 부분손실 가드 — 추출>0 이어도 package.json 누락 시 경고.

검증:
    P9-T1. 들여쓰기 ```bash + 직후 ```json(헤더) → package.json/tsconfig.json 추출 (회귀 박제).
    P9-T2. 추출된 package.json/tsconfig.json 이 유효 JSON (헤더 줄 제거).
    P9-T3. fence-info 파일명(```json package.json) 인식.
    P9-T4. well-known headerless json (compilerOptions/dependencies) 인식.
    P9-T5. .ts/.html/.css (헤더) 기존 동작 불변 — 헤더 줄 보존.
    P9-T6. 신호 없는 headerless 예시 json → 기존대로 드롭.
    P9-T7. _detect_extraction_loss — 부분 manifest 손실 경고 + 전손 경로 보존.
    P9-T8. python-only(Track A) 경로 불변 — json 무시.
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
    _detect_extraction_loss,
    _extract_code_blocks,
    _resolve_block_filename,
    _wellknown_json_name,
)

# 실제 P3 런 13_gui_code_output.md 구조 재현 — "- 추가 의존성:" 하위 2칸 들여쓰기된
# ```bash 블록(닫는 fence 도 들여쓰기) 직후 ```json(// file: 헤더) 두 블록.
_REAL_SCENARIO = (
    "### 1. 프레임워크 선택\n"
    "- 추가 의존성:\n"
    "  ```bash\n"
    "  npm install three web-ifc-three\n"
    "  ```\n"
    "\n"
    "### 2. 코드\n"
    "\n"
    "```json\n"
    "// file: package.json\n"
    '{\n  "name": "demo-viewer",\n'
    '  "scripts": {"dev": "vite", "build": "tsc && vite build"},\n'
    '  "dependencies": {"three": "^0.160.0"}\n}\n'
    "```\n"
    "\n"
    "```json\n"
    "// file: tsconfig.json\n"
    '{\n  "compilerOptions": {"target": "ES2022", "strict": true}\n}\n'
    "```\n"
    "\n"
    "```typescript\n"
    "// file: src/main.ts\n"
    'console.log("bim");\n'
    "```\n"
)


# =============================================================================
# P9-T1. 들여쓰기 ```bash + 직후 ```json → package.json/tsconfig.json 추출 (회귀 박제)
# =============================================================================
class TestT1IndentedFenceNoLongerDropsJson:
    def test_package_and_tsconfig_extracted(self, tmp_path: Path) -> None:
        saved = _extract_code_blocks(
            _REAL_SCENARIO, tmp_path, languages=_WEB_CODE_LANGS
        )
        names = {p.name for p in saved}
        # 진범(들여쓰기 fence desync) 수정 → 두 json 모두 추출
        assert "package.json" in names
        assert "tsconfig.json" in names
        # 그 뒤 web 파일도 정상 (re-sync 확인)
        assert "src__main.ts" in names
        # bash 는 _WEB_CODE_LANGS 에 없음 → 미추출 (정상)
        assert not any(p.suffix == ".sh" for p in saved)


# =============================================================================
# P9-T2. 추출된 json 이 유효 JSON (file: 헤더 줄 제거)
# =============================================================================
class TestT2ExtractedJsonIsValid:
    def test_package_json_valid_and_headerless(self, tmp_path: Path) -> None:
        _extract_code_blocks(_REAL_SCENARIO, tmp_path, languages=_WEB_CODE_LANGS)
        pkg_text = (tmp_path / "package.json").read_text(encoding="utf-8")
        assert "// file:" not in pkg_text  # 헤더 줄 제거됨
        data = json.loads(pkg_text)  # 유효 JSON (npm 파싱 가능)
        assert data["name"] == "demo-viewer"
        assert "build" in data["scripts"]

    def test_tsconfig_json_valid(self, tmp_path: Path) -> None:
        _extract_code_blocks(_REAL_SCENARIO, tmp_path, languages=_WEB_CODE_LANGS)
        ts = json.loads((tmp_path / "tsconfig.json").read_text(encoding="utf-8"))
        assert ts["compilerOptions"]["strict"] is True


# =============================================================================
# P9-T3. fence-info 파일명 (```json package.json)
# =============================================================================
class TestT3FenceInfoFilename:
    _MD = (
        "```json package.json\n"
        '{"name": "x", "dependencies": {"three": "^0.1.0"}}\n'
        "```\n"
    )

    def test_info_string_filename(self, tmp_path: Path) -> None:
        saved = {p.name for p in _extract_code_blocks(self._MD, tmp_path, languages=_WEB_CODE_LANGS)}
        assert "package.json" in saved
        # info-string 경로는 헤더 줄이 없어 본문 그대로 → 유효 JSON
        assert json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))["name"] == "x"

    def test_resolve_returns_info_name(self) -> None:
        name, strip = _resolve_block_filename("json", "package.json", '{"name": "x"}')
        assert name == "package.json" and strip is False


# =============================================================================
# P9-T4. well-known headerless json (내용 식별)
# =============================================================================
class TestT4WellknownHeaderlessJson:
    _MD = (
        "```json\n"
        '{"compilerOptions": {"strict": true}}\n'
        "```\n"
        "\n"
        "```json\n"
        '{"name": "y", "scripts": {"build": "vite build"}}\n'
        "```\n"
    )

    def test_content_recognized(self, tmp_path: Path) -> None:
        saved = {p.name for p in _extract_code_blocks(self._MD, tmp_path, languages=_WEB_CODE_LANGS)}
        assert "tsconfig.json" in saved  # compilerOptions
        assert "package.json" in saved  # name+scripts

    def test_wellknown_helper(self) -> None:
        assert _wellknown_json_name('{"compilerOptions": {}}') == "tsconfig.json"
        assert _wellknown_json_name('{"dependencies": {"a": "1"}}') == "package.json"
        assert _wellknown_json_name('{"name": "z", "scripts": {}}') == "package.json"
        assert _wellknown_json_name('{"foo": 1, "bar": 2}') is None


# =============================================================================
# P9-T5. .ts/.html/.css (헤더) 기존 동작 불변 — 헤더 줄 보존
# =============================================================================
class TestT5WebFilesUnchanged:
    _MD = (
        "```typescript\n// file: src/app.ts\nexport const x = 1;\n```\n"
        "\n"
        "```html\n<!-- file: index.html -->\n<!doctype html><html></html>\n```\n"
        "\n"
        "```css\n/* file: src/styles.css */\nbody { color: red; }\n```\n"
    )

    def test_names_and_headers_preserved(self, tmp_path: Path) -> None:
        saved = {p.name: p for p in _extract_code_blocks(self._MD, tmp_path, languages=_WEB_CODE_LANGS)}
        assert set(saved) == {"src__app.ts", "index.html", "src__styles.css"}
        # 비-json 은 file: 헤더 줄 보존 (기존 동작 불변 — 회귀 0)
        assert saved["src__app.ts"].read_text(encoding="utf-8").startswith("// file: src/app.ts")
        assert saved["index.html"].read_text(encoding="utf-8").startswith("<!-- file: index.html -->")
        assert saved["src__styles.css"].read_text(encoding="utf-8").startswith("/* file: src/styles.css */")


# =============================================================================
# P9-T6. 신호 없는 headerless 예시 json → 기존대로 드롭
# =============================================================================
class TestT6HeaderlessExampleDropped:
    _MD = "```json\n" '{"sampleData": [1, 2, 3], "note": "example"}\n' "```\n"

    def test_example_json_dropped(self, tmp_path: Path) -> None:
        saved = _extract_code_blocks(self._MD, tmp_path, languages=_WEB_CODE_LANGS)
        assert saved == []  # well-known/헤더/info 신호 없음 → 드롭 (기존 가드 보존)


# =============================================================================
# P9-T7. _detect_extraction_loss — 부분 manifest 손실 + 전손 경로 보존
# =============================================================================
class TestT7DetectExtractionLoss:
    def test_partial_manifest_loss_warns(self, tmp_path: Path) -> None:
        # web 일부 저장됐으나 package.json 미저장 → 부분손실 경고
        saved = [tmp_path / "src__main.ts"]
        warn = _detect_extraction_loss(_REAL_SCENARIO, saved)
        assert warn is not None
        assert "package.json" in warn and "manifest" in warn.lower()

    def test_no_warn_when_package_json_saved(self, tmp_path: Path) -> None:
        saved = [tmp_path / "src__main.ts", tmp_path / "package.json"]
        assert _detect_extraction_loss(_REAL_SCENARIO, saved) is None

    def test_total_loss_path_preserved(self) -> None:
        # web 헤더 다수 + 추출 0개 → 기존 전손 경고 (P2-A)
        warn = _detect_extraction_loss(_REAL_SCENARIO, [])
        assert warn is not None and "0개" in warn


# =============================================================================
# P9-T8. python-only(Track A) 경로 불변 — json 무시
# =============================================================================
class TestT8PythonOnlyUnchanged:
    _MD = (
        "```python\n# file: calc.py\nprint(1)\n```\n"
        "\n"
        "```json\n// file: package.json\n" '{"name": "z"}\n' "```\n"
    )

    def test_default_langs_python_only(self, tmp_path: Path) -> None:
        # 기본 languages=_PY_ONLY_LANGS → python 만, json 무시 (Track A/release 회귀 0)
        saved = {p.name for p in _extract_code_blocks(self._MD, tmp_path)}
        assert saved == {"calc.py"}
