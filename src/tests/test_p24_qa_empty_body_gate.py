# -*- coding: utf-8 -*-
"""v13 P24 — QA 빈 NEEDS_REVISION 박멸 회귀 test.

진단(ERP 런 alpha_run_20260604_132514): 04_qa_review.md 3개 중 1개(151255)가 14바이트
"NEEDS_REVISION" 단독 = 빈 본문(layer ① LLM 생성). 빈 본문이 다음 iteration(Gap Analyst)에
전파되면 루프가 깜깜이가 된다.

검증:
  - 감지(qa_review_body_is_empty): verdict-only / 헤더만 / 플레이스홀더 → True, 실 항목 / APPROVED → False.
  - 스키마(② CodeReviewOutput): NEEDS_REVISION + 빈 §3/§4 → ValidationError (CrewAI 재요청).
  - 안전망(_maybe_regenerate_on_qa_empty_body): 빈 본문 → 재생성 회복 / 소진 시 *비어있지 않은*
    보강 본문 + fail-loud 아티팩트. 정상 본문 → no-op(회귀 0). pytest 는 실 Crew 미호출.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows._schemas import (  # noqa: E402
    CodeReviewOutput,
    _canon_verdict,
    _qa_line_is_substantive,
    _qa_verdict_of,
    qa_review_body_is_empty,
)
from src.workflows.analyze_and_implement import (  # noqa: E402
    _build_qa_empty_body_directive,
    _maybe_regenerate_on_qa_empty_body,
    _synthesize_qa_fallback_body,
)

# 실 항목을 채운 정상 NEEDS_REVISION (>40자 본문)
_FULL_REVIEW = (
    "Final Answer: NEEDS_REVISION\n\n## 코드 리뷰 보고서\n\n"
    "### 1. 종합 판정\nNEEDS_REVISION. 킥오프(PySide6)와 구현(Tkinter) 불일치.\n\n"
    "### 3. 발견된 이슈\n- **[BLOCKER]** `app/main.py:12` — Tkinter 사용, PySide6 합의 위반 "
    "→ 표현 계층 전체를 PySide6 로 교체.\n\n"
    "### 4. 권장 보정\n1. main.py 위젯을 QtWidgets 로 포팅.\n"
)


# =============================================================================
# 1. 감지 — qa_review_body_is_empty
# =============================================================================
class TestQaBodyEmptyDetector:
    def test_verdict_only_14byte_is_empty(self) -> None:
        """ERP 151255 실제 케이스 — 14바이트 'NEEDS_REVISION' 단독."""
        assert qa_review_body_is_empty("NEEDS_REVISION") is True

    def test_headers_only_to_markdown_is_empty(self) -> None:
        """to_markdown 헤더 스캐폴드만(본문 필드 빈 값) → 총길이는 길어도 빈 본문."""
        headers_only = (
            "NEEDS_REVISION\n\n## 코드 리뷰 보고서\n\n### 1. 종합 판정\n\n"
            "### 2. 항목별 점검 결과\n\n### 3. 발견된 이슈\n\n### 4. 권장 보정\n\n### 5. 미검토 영역\n"
        )
        assert qa_review_body_is_empty(headers_only) is True

    def test_placeholder_body_is_empty(self) -> None:
        """<본문>/... 플레이스홀더만 → 빈 본문."""
        ph = "Final Answer: NEEDS_REVISION\n\n## 코드 리뷰 보고서\n### 1. 종합 판정\n<본문>\n### 3. 발견된 이슈\n...\n"
        assert qa_review_body_is_empty(ph) is True

    def test_full_body_is_not_empty(self) -> None:
        assert qa_review_body_is_empty(_FULL_REVIEW) is False

    def test_approved_empty_is_not_gated(self) -> None:
        """APPROVED 는 본문이 짧아도 게이트 비대상(회귀 0)."""
        assert qa_review_body_is_empty("APPROVED") is False
        assert qa_review_body_is_empty("Final Answer: APPROVED\n\n## 보고서\n간단.") is False

    def test_empty_string_not_gated(self) -> None:
        """빈 산출은 verdict 미상 → QA 게이트 비대상(단축 가드 영역)."""
        assert qa_review_body_is_empty("") is False
        assert qa_review_body_is_empty("   ") is False

    # --- 적대 리뷰(fake-body/parser) 가 잡은 verdict 변형: 빈 본문이 위장 통과하면 안 됨 ---
    @pytest.mark.parametrize(
        "verdict_only",
        [
            "NEEDS_REVISION (HIGH=1, MEDIUM=2)",          # 파라메트릭 카운트
            "Final Answer: NEEDS_REVISION (CRITICAL=1, HIGH=2)",  # few-shot 형태
            "NEEDS_REVISION:",                            # 콜론
            "NEEDS_REVISION.",                            # 마침표
            "**NEEDS_REVISION**",                         # 강조
            "NEEDS REVISION",                             # 공백 변형
            "결과: NEEDS_REVISION",                        # 라벨 prefix
        ],
    )
    def test_verdict_only_variants_are_empty(self, verdict_only: str) -> None:
        """구두점/강조/공백/파라메트릭 변형의 verdict-only → 모두 빈 본문(게이트 활성)."""
        assert qa_review_body_is_empty(verdict_only) is True

    def test_header_first_no_final_answer_is_detected(self) -> None:
        """헤더가 verdict 보다 앞서고 Final Answer 줄이 없어도(이슈4 회귀형) 게이트가 잡는다."""
        text = "## 코드 리뷰 보고서\nNEEDS_REVISION\n### 3. 발견된 이슈\n"
        assert qa_review_body_is_empty(text) is True

    def test_no_issue_phrases_as_body_are_empty(self) -> None:
        """흔한 한국어 no-issue 문구만 있는 NEEDS_REVISION → 빈 본문."""
        for body in ["이슈 없음", "특이사항 없음", "없습니다", "수정 불필요", "발견된 이슈 없음"]:
            text = f"NEEDS_REVISION\n\n### 3. 발견된 이슈\n{body}\n### 4. 권장 보정\n{body}\n"
            assert qa_review_body_is_empty(text) is True, body

    def test_no_issue_prose_is_preserved(self) -> None:
        """R2 트레이드오프: 'no-issue' 산문 *한 문장* 은 실 내용 줄로 보존(빈 본문 아님).

        줄 단위 no-issue 휴리스틱은 동일 줄의 실 finding 까지 드롭하는 R2 회귀를 냈으므로,
        실 리뷰 *보존* 을 우선한다. (generation validator·convergence judge 가 보조.)
        """
        text = (
            "NEEDS_REVISION\n\n### 3. 발견된 이슈\n"
            "코드를 전반적으로 검토한 결과 특별히 발견된 이슈는 없습니다.\n"
        )
        assert qa_review_body_is_empty(text) is False

    def test_short_real_review_with_fileline_is_not_empty(self) -> None:
        """40자 미만 + 파일:라인 실재 리뷰는 빈 본문이 아니다 (보일러플레이트 덮어쓰기 방지)."""
        text = "NEEDS_REVISION\n### 3. 발견된 이슈\n- main.py:12 Tkinter\n### 4. 권장 보정\n- PySide6\n"
        assert qa_review_body_is_empty(text) is False

    def test_short_real_review_WITHOUT_fileline_is_not_empty(self) -> None:
        """R2 핵심 수정: 파일:라인/태그 없는 *짧은 실 finding* 도 보존(길이 임계 폐지)."""
        for body in [
            "로그인 함수에 입력 검증 없음",       # 실 finding(검증 누락) — '없음' 끼어도 보존
            "DB 연결 예외 처리가 빠졌습니다.",
            "Tkinter 대신 PySide6 써야 함.",
            "NEEDS_REVISION 사유로 main.py 빌드가 깨졌습니다",
        ]:
            text = f"NEEDS_REVISION\n### 3. 발견된 이슈\n{body}\n"
            assert qa_review_body_is_empty(text) is False, body

    def test_cooccurring_real_finding_is_preserved(self) -> None:
        """R2 high: 같은 줄에 'X 없음. 그러나 Y 위험' 이 와도 실 finding(Y)이 보존되어 빈 본문 아님."""
        text = (
            "Final Answer: NEEDS_REVISION\n### 3. 발견된 이슈\n"
            "SQL injection 위반사항 없음. 그러나 XSS 위험 존재.\n### 4. 권장 보정\n출력 이스케이프 적용.\n"
        )
        assert qa_review_body_is_empty(text) is False

    def test_short_severity_tag_review_is_not_empty(self) -> None:
        """심각도 태그가 있는 짧은 리뷰도 본문 있음."""
        text = "NEEDS_REVISION\n### 3\n- [BLOCKER] 빌드 실패\n"
        assert qa_review_body_is_empty(text) is False

    def test_prose_real_review_is_not_empty(self) -> None:
        """파일:라인 없이도 구체적인 실 보정 프로즈는 본문 있음."""
        text = (
            "NEEDS_REVISION\n### 3. 발견된 이슈\n"
            "킥오프는 PySide6 합의인데 구현이 Tkinter 라 표현 계층 전체를 PySide6 로 교체해야 합니다.\n"
        )
        assert qa_review_body_is_empty(text) is False

    def test_no_redos_all_paths(self) -> None:
        """R3 #8/#11 + R4 #1: 취약 경로를 *실제로* 행사하는 ReDoS 회귀 가드(선형/서브초).

        - placeholder 한글 no-issue prefix + 공백런('발견' + spaces) — R4 #1 의 3중 \\s* 폭발 경로
        - placeholder 대시 런 — R3 #8
        - verdict 줄 카운트괄호 런 — R3 #11
        - 긴 일반 라인
        (이전 redos 테스트는 단어-선두 입력이라 취약 경로를 건드리지 못해 false-green 이었음.)
        """
        import time
        t0 = time.perf_counter()
        qa_review_body_is_empty("Final Answer: NEEDS_REVISION\n### 3. 발견된 이슈\n발견" + (" " * 64000) + "x\n")
        qa_review_body_is_empty("Final Answer: NEEDS_REVISION\n### 3\n발견된 이슈는" + ("\t" * 20000) + "z\n")
        qa_review_body_is_empty("NEEDS_REVISION\n### 3. 발견된 이슈\n" + ("-" * 5000) + "x없\n")
        qa_review_body_is_empty("Final Answer: NEEDS_REVISION\n### 3\n" + "NEEDS_REVISION (" + "HIGH=1, " * 8000)
        qa_review_body_is_empty("NEEDS_REVISION\n### 3\n" + ("a" * 100000) + ".:/-x" * 20000 + "\n")
        assert time.perf_counter() - t0 < 1.0

    def test_R4_2_huge_section_number_no_crash(self) -> None:
        """R4 #2: 거대한 자릿수 섹션 헤더(#9999...)에서 int() ValueError 없이 bool 반환."""
        out = qa_review_body_is_empty("NEEDS_REVISION\n#" + "9" * 200000 + ". x\n")
        assert out in (True, False)

    def test_R4_3_section_header_precision(self) -> None:
        """R4 #3: '### 3가지...'(숫자에 한글 연접)는 섹션 헤더로 오인하지 않음."""
        import src.workflows._schemas as sc
        assert sc._QA_SECTION_HEADER_RE.match("### 3가지 핵심 이슈") is None
        assert sc._QA_SECTION_HEADER_RE.match("### 3. 발견된 이슈") is not None
        assert sc._QA_SECTION_HEADER_RE.match("### 3") is not None

    def test_R4_5_approved_progression_not_flipped(self) -> None:
        """R4 #5: 'NEEDS_REVISION 해소 → APPROVED'(승인 전환)는 빈 NEEDS_REVISION 으로 게이팅되지 않음."""
        text = "Final Answer: 직전 NEEDS_REVISION 해소 → APPROVED\n### 3\n\n### 4\n\n"
        assert qa_review_body_is_empty(text) is False

    def test_R4_6_quoted_final_answer_ignored(self) -> None:
        """R4 #6: 산문 중간에 인용된 'Final Answer: NEEDS_REVISION' 은 verdict 로 채택하지 않음(줄머리만)."""
        text = "Final Answer: APPROVED\n### 3\n발견된 이슈 없음\n직전 라운드는 Final Answer: NEEDS_REVISION 였음.\n"
        assert _qa_verdict_of(text) == "APPROVED"
        assert qa_review_body_is_empty(text) is False

    def test_R4_7_prose_approved_with_nr_mention_not_gated(self) -> None:
        """R4 #7: 산문으로 승인하며 NEEDS_REVISION 을 언급해도(APPROVED 흔적 존재) 게이트 비대상."""
        text = (
            "## 코드 리뷰 보고서\n### 1. 종합 판정\n"
            "검토 결과 APPROVED 로 판단합니다. NEEDS_REVISION 사유였던 타입힌트는 보완됨.\n"
            "### 3. 발견된 이슈\n발견된 이슈 없음\n"
        )
        assert qa_review_body_is_empty(text) is False

    def test_R4_pure_nr_ambiguous_empty_still_gated(self) -> None:
        """대조군: APPROVED 흔적 없는 모호 NEEDS_REVISION + 빈 §3/§4 는 여전히 빈 본문으로 게이트."""
        assert qa_review_body_is_empty("NEEDS_REVISION 회귀\n### 3\n\n### 4\n\n") is True


class TestR5Hardening:
    """5차 적대 리뷰가 잡은 회귀 (KO-tail ReDoS·단어경계·번호없는 헤더·인라인 finding)."""

    def test_R5_ko_tail_redos_actually_exercised(self) -> None:
        """R5 #1/#2/#4: verdict-선도 줄 + '으로' + 공백런(KO-tail 경로를 *실제로* 행사)이 선형/서브초.

        (R4 의 redos 테스트는 verdict 토큰 선도가 아니라 _qa_verdict_only_token 조기반환으로 KO-tail
        에 도달 못 해 false-green 이었음 — 이번엔 'NEEDS_REVISION 으로 ...' 로 반드시 도달.)
        """
        import time
        t0 = time.perf_counter()
        qa_review_body_is_empty("Final Answer: NEEDS_REVISION\n### 3. 발견된 이슈\nNEEDS_REVISION 으로" + (" " * 64000) + "x\n")
        qa_review_body_is_empty("NEEDS_REVISION 으로" + (" " * 64000) + "x")
        qa_review_body_is_empty("APPROVED 발견" + ("\t" * 40000) + "z")
        assert time.perf_counter() - t0 < 1.0

    def test_R5_7_word_boundary_unapproved_not_approval(self) -> None:
        """R5 #7: 산문의 'unapproved/disapproved/pre-approved' 는 APPROVED 토큰이 아니다.

        단어경계가 없으면 가짜 APPROVED 흔적이 모호-verdict 게이트를 꺼서 빈 NEEDS_REVISION 이 누수.
        """
        import src.workflows._schemas as sc
        assert sc._qa_text_has_approved("unapproved external dependency") is False
        assert sc._qa_text_has_approved("disapproved pattern") is False
        assert sc._qa_text_has_approved("pre-approved") is False
        assert sc._qa_text_has_approved("Final Answer: APPROVED") is True
        # 게이트: 모호 NEEDS_REVISION + 빈 §3/§4 + 산문에 'unapproved' → 여전히 빈 본문으로 게이트
        text = (
            "NEEDS_REVISION 수준의 문제\n### 3. 발견된 이슈\n\n### 4. 권장 보정\n\n"
            "### 5. 미검토 영역\nunapproved 외부 의존성 스캔은 미검토.\n"
        )
        assert qa_review_body_is_empty(text) is True

    def test_R5_3_unnumbered_status_header_skipped(self) -> None:
        """R5 #3: 번호 없는 헤더('### 항목별 점검 결과')도 상태표로 인식 → §2-only 빈 NR 게이트."""
        text = (
            "Final Answer: NEEDS_REVISION\n### 발견된 이슈\n\n### 권장 보정\n\n"
            "### 항목별 점검 결과\n| 1 | 타입 | OK |\n"
        )
        assert qa_review_body_is_empty(text) is True
        # 대조군: 번호 없는 actionable 헤더 아래 실 이슈는 보존
        real = "Final Answer: NEEDS_REVISION\n### 발견된 이슈\n- app.py:8 하드코딩 키\n"
        assert qa_review_body_is_empty(real) is False

    def test_R5_5_inline_header_finding_preserved(self) -> None:
        """R5 #5: §3/§4 헤더 *같은 줄* 콜론 뒤에 적은 실 finding 이 폐기되지 않고 보존."""
        text = (
            "Final Answer: NEEDS_REVISION\n## 보고서\n"
            "### 3. 발견된 이슈: app.py:8 하드코딩 키, db.py:30 SQL 인젝션\n"
            "### 4. 권장 보정: env 이전, 바인드 파라미터\n"
        )
        assert qa_review_body_is_empty(text) is False


class TestR6Hardening:
    """6차 적대 리뷰가 잡은 회귀 (approval 식별자 누수·'점검' 제목 오분류·잔여 ③ 명문화)."""

    @pytest.mark.parametrize("ident", ["is_approved", "approved_at", "approved2", "approved_list", "self.approved_count"])
    def test_R6_1_code_identifiers_not_approval_tokens(self, ident: str) -> None:
        """R6 #1: 'is_approved'·'approved_at' 등 코드 식별자는 APPROVED 토큰이 아니다(단어경계에 _/숫자 포함).

        ERP 코드 리뷰에 승인-상태 컬럼(is_approved/approved_at)이 흔하므로, 이게 APPROVED 흔적으로
        오인되면 모호 verdict 의 빈 NEEDS_REVISION 이 게이트를 우회한다.
        """
        import src.workflows._schemas as sc
        assert sc._qa_text_has_approved(ident) is False

    def test_R6_1_approved_identifier_does_not_disable_gate(self) -> None:
        """R6 #1 게이트: 모호 NEEDS_REVISION + 빈 §3/§4 + 본문에 is_approved 식별자 → 여전히 빈 본문."""
        text = (
            "## 코드 리뷰 보고서\n### 1. 종합 판정\nNEEDS_REVISION 으로 보이나 추가 확인 필요.\n"
            "### 3. 발견된 이슈\n\n### 4. 권장 보정\n\n### 5. 미검토 영역\nis_approved 플래그 경로는 미검토.\n"
        )
        assert qa_review_body_is_empty(text) is True
        # 대조군: 진짜 APPROVED 토큰은 여전히 게이트를 끈다
        import src.workflows._schemas as sc
        assert sc._qa_text_has_approved("Final Answer: APPROVED") is True

    @pytest.mark.parametrize(
        "header",
        ["### 취약점 점검", "### 정적 점검에서 발견된 취약점", "### 보안 점검 결과 발견된 이슈", "### 결함 점검"],
    )
    def test_R6_2_actionable_keyword_beats_status_keyword(self, header: str) -> None:
        """R6 #2/#3: 번호 없는 헤더에 '점검'+actionable 키워드가 섞이면 actionable 로 분류(실 finding 보존)."""
        import src.workflows._schemas as sc
        assert sc._qa_header_info(header)[1] == "actionable"

    def test_R6_3_findings_under_inspection_titled_header_preserved(self) -> None:
        """R6 #3: '점검' 글자가 섞인 번호 없는 발견-섹션 아래의 실 finding 이 빈 본문으로 오판되지 않음."""
        text = (
            "Final Answer: NEEDS_REVISION\n## 보안 감사 보고서\n### 정적 점검에서 발견된 취약점\n"
            "- [CRITICAL] app.py:8 하드코딩 API 키\n- [HIGH] db.py:30 SQL 인젝션\n"
        )
        assert qa_review_body_is_empty(text) is False

    def test_R6_3_pure_status_header_still_status(self) -> None:
        """대조군: actionable 키워드 없는 순수 점검표 제목은 여전히 status(§2)로 인식."""
        import src.workflows._schemas as sc
        assert sc._qa_header_info("### 항목별 점검 결과")[1] == "status"
        assert sc._qa_header_info("### 2. 항목별 점검")[1] == "status"

    @pytest.mark.parametrize(
        "ident", ["approved-at", "approved-flag", "user.approved", "approved.status", "approved.py", "approved.count"],
    )
    def test_R7_hyphen_dot_identifiers_not_approval(self, ident: str) -> None:
        """R7: 하이픈/점 인접 승인 식별자(approved-at·user.approved·approved.py)도 APPROVED 토큰 아님."""
        import src.workflows._schemas as sc
        assert sc._qa_text_has_approved(ident) is False

    @pytest.mark.parametrize("legit", ["Final Answer: APPROVED", "APPROVED.", "APPROVED. 모든 항목 충족", "**APPROVED**"])
    def test_R7_legit_approved_forms_preserved(self, legit: str) -> None:
        """대조군: 문장 종결 'APPROVED.'·강조 '**APPROVED**' 등 정당한 승인 형태는 보존."""
        import src.workflows._schemas as sc
        assert sc._qa_text_has_approved(legit) is True

    def test_R7_2_status_table_with_actionable_keyword_title(self) -> None:
        """R7 #2: actionable 키워드가 섞인 *점검표* 제목('이슈 점검표')은 status — §2 escape 차단."""
        import src.workflows._schemas as sc
        assert sc._qa_header_info("### 이슈 점검표")[1] == "status"
        assert sc._qa_header_info("### 항목별 점검 결과")[1] == "status"
        # 그러나 점검표 어구가 아닌 '취약점 점검'·'발견된 취약점' 은 여전히 actionable(R6#2/#3 유지)
        assert sc._qa_header_info("### 취약점 점검")[1] == "actionable"
        assert sc._qa_header_info("### 정적 점검에서 발견된 취약점")[1] == "actionable"
        # e2e: 점검표만 + 빈 §4 → 빈 본문 게이트
        assert qa_review_body_is_empty(
            "Final Answer: NEEDS_REVISION\n### 이슈 점검표\n| 1 | 타입 | OK |\n### 권장 보정\n\n"
        ) is True

    def test_R6_5_residual_nonenglish_approval_documented(self) -> None:
        """R6 #5: 의도된 잔여 ③ 명문화 — 비영문 승인(승인/OK)은 APPROVED 흔적으로 *인식 안 됨*.

        프롬프트가 영문 Final Answer 를 강제하므로 off-spec. 한국어 '승인' + 잔류 NR + 빈 §3/§4 는
        (영문 APPROVED 흔적이 없어) 빈 본문으로 게이트된다 — 현재 동작을 고정해 정책 변경을 surface.
        """
        import src.workflows._schemas as sc
        assert sc._qa_text_has_approved("승인합니다") is False
        assert sc._qa_text_has_approved("OK 합격") is False
        text = "승인합니다. 직전 NEEDS_REVISION 해소.\n### 3. 발견된 이슈\n\n### 4. 권장 보정\n\n"
        assert qa_review_body_is_empty(text) is True


class TestVerdictNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("NEEDS_REVISION", "NEEDS_REVISION"),
            ("NEEDS_REVISION (HIGH=1)", "NEEDS_REVISION"),
            ("NEEDS_REVISION:", "NEEDS_REVISION"),
            ("NEEDS_REVISION.", "NEEDS_REVISION"),
            ("**NEEDS_REVISION**", "NEEDS_REVISION"),
            ("NEEDS REVISION", "NEEDS_REVISION"),
            ("needs_revision", "NEEDS_REVISION"),
            ("APPROVED", "APPROVED"),
            ("approved.", "APPROVED"),
            ("", ""),
            ("UNKNOWN", ""),
            # R2 verdict-norm: 두 토큰 공존 → 모호('') 로 처리(정상 승인 거짓 거부 방지)
            ("NEEDS_REVISION 해소됨 → APPROVED", ""),
            ("이전 NEEDS_REVISION. 이제 APPROVED.", ""),
        ],
    )
    def test_canon_verdict(self, raw: str, expected: str) -> None:
        assert _canon_verdict(raw) == expected

    def test_qa_verdict_of_skips_headers(self) -> None:
        assert _qa_verdict_of("## 보고서\n### 1.\nNEEDS_REVISION (HIGH=1)") == "NEEDS_REVISION"
        assert _qa_verdict_of("Final Answer: APPROVED\n## 보고서") == "APPROVED"

    def test_qa_verdict_of_scans_past_prose_to_real_verdict(self) -> None:
        """R2 verdict-norm: 산문/헤더 선행 후의 *진짜* verdict-only 줄을 포착(첫 줄 조기종료 X)."""
        assert _qa_verdict_of("검토를 시작합니다.\nAPPROVED\n") == "APPROVED"
        assert _qa_verdict_of("## 보고서\n지난 NEEDS_REVISION 처리\nAPPROVED\n") == "APPROVED"
        assert _qa_verdict_of("QA 검토 진행.\nNEEDS_REVISION\n") == "NEEDS_REVISION"


# =============================================================================
# 2. 스키마(②) — CodeReviewOutput model_validator
# =============================================================================
class TestCodeReviewOutputValidator:
    def _build(self, **over):
        base = dict(
            verdict="NEEDS_REVISION", overall_assessment="요약",
            item_check_table="| 1 | 타입 | ✅ |", issues_found="없음",
            recommended_fixes="해당 없음", out_of_scope="없음",
        )
        base.update(over)
        return base

    def test_needs_revision_empty_body_rejected(self) -> None:
        """NEEDS_REVISION + §3·§4 모두 빈/플레이스홀더 → ValidationError (생성 단계 차단)."""
        with pytest.raises(ValidationError):
            CodeReviewOutput(**self._build(issues_found="", recommended_fixes=""))
        with pytest.raises(ValidationError):
            CodeReviewOutput(**self._build(issues_found="해당 없음", recommended_fixes="..."))

    @pytest.mark.parametrize("verdict", ["NEEDS_REVISION (HIGH=1)", "NEEDS_REVISION:", "needs_revision"])
    def test_variant_verdict_empty_body_rejected(self, verdict: str) -> None:
        """파라메트릭/구두점/소문자 verdict 변형도 빈 본문이면 거부(정규화 공유)."""
        with pytest.raises(ValidationError):
            CodeReviewOutput(**self._build(verdict=verdict, issues_found="이슈 없음", recommended_fixes="없음"))

    def test_no_issue_phrase_fields_rejected(self) -> None:
        """흔한 한국어 no-issue 단문 필드(이슈 없음/수정 불필요)도 빈 것으로 거부."""
        with pytest.raises(ValidationError):
            CodeReviewOutput(**self._build(issues_found="특이사항 없음", recommended_fixes="수정 불필요"))

    def test_needs_revision_with_items_ok(self) -> None:
        out = CodeReviewOutput(**self._build(
            issues_found="- [BLOCKER] app/main.py:12 — Tkinter, PySide6 로 교체",
            recommended_fixes="1. main.py 포팅",
        ))
        assert out.verdict == "NEEDS_REVISION"

    def test_approved_empty_fixes_ok(self) -> None:
        """APPROVED 면 recommended_fixes='해당 없음' 정상(비대상)."""
        out = CodeReviewOutput(**self._build(verdict="APPROVED", issues_found="발견된 이슈 없음"))
        assert out.verdict == "APPROVED"

    def test_both_token_verdict_not_falsely_rejected(self) -> None:
        """R2 verdict-norm: verdict 필드에 두 토큰 공존(승인 의도)이면 거짓 거부하지 않는다."""
        out = CodeReviewOutput(**self._build(
            verdict="NEEDS_REVISION 해소됨 → APPROVED", issues_found="없음", recommended_fixes="해당 없음",
        ))
        assert out.verdict.endswith("APPROVED")

    def test_validator_pass_implies_gate_nonempty(self) -> None:
        """R2 #13: validator 통과(실 finding) ⇒ 게이트도 non-empty — 두 레이어 빈-본문 기준 일치."""
        out = CodeReviewOutput(**self._build(
            issues_found="DB 연결 예외 처리가 빠졌습니다.", recommended_fixes="try/except 추가.",
        ))
        assert qa_review_body_is_empty(out.to_markdown()) is False


# =============================================================================
# 3. 안전망 — _maybe_regenerate_on_qa_empty_body
# =============================================================================
class TestQaEmptyBodyActuator:
    def test_noop_when_body_present(self, tmp_path: Path) -> None:
        """정상 본문 → no-op, _regen_fn 미호출 (회귀 0)."""
        called = []
        out = _maybe_regenerate_on_qa_empty_body(
            SimpleNamespace(), _FULL_REVIEW, workflow_dir=tmp_path, verbose=False,
            _regen_fn=lambda t: called.append(1) or "x",
        )
        assert out == _FULL_REVIEW and not called

    def test_recovers_on_retry(self, tmp_path: Path) -> None:
        """빈 본문 → 재생성이 실 항목을 내면 채택(회복)."""
        out = _maybe_regenerate_on_qa_empty_body(
            SimpleNamespace(), "NEEDS_REVISION", workflow_dir=tmp_path, verbose=False,
            _regen_fn=lambda t: _FULL_REVIEW,
        )
        assert out == _FULL_REVIEW
        assert qa_review_body_is_empty(out) is False

    def test_fallback_when_retry_still_empty(self, tmp_path: Path) -> None:
        """재시도 소진 후에도 비면 → *비어있지 않은* 보강 본문 + fail-loud 아티팩트. 전파 차단."""
        out = _maybe_regenerate_on_qa_empty_body(
            SimpleNamespace(), "NEEDS_REVISION", workflow_dir=tmp_path, verbose=False,
            _regen_fn=lambda t: "NEEDS_REVISION", max_retries=1,
        )
        assert qa_review_body_is_empty(out) is False  # 빈 본문 절대 전파 안 함
        assert "자동 보강" in out
        assert (tmp_path / "04b_qa_empty_body.txt").exists()

    def test_pytest_shortcircuit_when_no_regen_fn(self, tmp_path: Path) -> None:
        """_regen_fn 미주입 + pytest → 실 Crew 미호출(프로덕션 전용). 입력 그대로."""
        out = _maybe_regenerate_on_qa_empty_body(
            SimpleNamespace(), "NEEDS_REVISION", workflow_dir=tmp_path, verbose=False,
        )
        assert out == "NEEDS_REVISION"

    def test_regen_exception_still_yields_nonempty_fallback(self, tmp_path: Path) -> None:
        """_regen_fn 이 예외를 던져도(LLM 타임아웃 등) 빈 본문을 전파하지 않고 보강 본문 반환."""
        def _boom(_t):
            raise RuntimeError("LLM timeout")

        out = _maybe_regenerate_on_qa_empty_body(
            SimpleNamespace(), "NEEDS_REVISION", workflow_dir=tmp_path, verbose=False,
            _regen_fn=_boom, max_retries=2,
        )
        assert qa_review_body_is_empty(out) is False
        assert (tmp_path / "04b_qa_empty_body.txt").exists()

    def test_retry_count_matches_max_retries(self, tmp_path: Path) -> None:
        """빈 본문이 지속되면 _regen_fn 이 정확히 max_retries 회 호출된다."""
        calls = []
        _maybe_regenerate_on_qa_empty_body(
            SimpleNamespace(), "NEEDS_REVISION", workflow_dir=tmp_path, verbose=False,
            _regen_fn=lambda t: calls.append(1) or "NEEDS_REVISION", max_retries=3,
        )
        assert len(calls) == 3

    def test_synthesized_fallback_is_actionable_and_passes_gate(self) -> None:
        """합성 보강 본문 자체는 비어있지 않고 게이트를 통과 + verdict=NEEDS_REVISION 보존."""
        fb = _synthesize_qa_fallback_body("NEEDS_REVISION")
        assert qa_review_body_is_empty(fb) is False
        assert "권장 보정" in fb and "발견된 이슈" in fb
        assert _qa_verdict_of(fb) == "NEEDS_REVISION"  # 다음 iter 루프 지속을 위한 verdict 보존


class TestQaEmptyBodyDirective:
    def test_directive_demands_concrete_items(self) -> None:
        """재생성 directive(프로덕션 회복의 유일 장치)가 핵심 강제 토큰을 포함(P16 패턴)."""
        d = _build_qa_empty_body_directive()
        for token in ["발견된 이슈", "권장 보정", "BLOCKER", "파일:라인", "플레이스홀더"]:
            assert token in d, token


# 5단 to_markdown 스캐폴드(verdict/§1~§5 본문을 채워 넣는다)
def _md(verdict="NEEDS_REVISION", s1="", s2="", s3="", s4="", s5=""):
    return (
        f"{verdict}\n\n## 코드 리뷰 보고서\n\n"
        f"### 1. 종합 판정\n\n{s1}\n\n### 2. 항목별 점검 결과\n\n{s2}\n\n"
        f"### 3. 발견된 이슈\n\n{s3}\n\n### 4. 권장 보정\n\n{s4}\n\n### 5. 미검토 영역\n\n{s5}\n"
    )


class TestR3Hardening:
    """3차 적대 리뷰가 잡은 회귀/우회를 고정 (verdict 재진술·copula·ReDoS·§2-only·PySide6 등)."""

    def test_R3_1_verdict_restatement_line_not_substantive(self) -> None:
        """§1 에 verdict 를 재진술('NEEDS_REVISION 으로 판정합니다')만 하고 §3/§4 비면 빈 본문."""
        assert qa_review_body_is_empty(_md(s1="NEEDS_REVISION 으로 판정합니다.")) is True

    @pytest.mark.parametrize("text", ["NEEDS_REVISION 입니다", "NEEDS_REVISION 으로 판정합니다.", "NEEDS_REVISION 임"])
    def test_R3_2_korean_copula_verdict_still_gated(self, text: str) -> None:
        """'NEEDS_REVISION 입니다' 류(종결어미 부착)도 게이트가 NEEDS_REVISION 빈 본문으로 인식."""
        assert qa_review_body_is_empty(text) is True

    def test_R3_3_bare_digits_not_substantive(self) -> None:
        """숫자/언더스코어/기호만 있는 줄은 실 내용 아님 — junk body 가 게이트를 우회 못 함."""
        assert qa_review_body_is_empty(_md(s3="0", s4="0")) is True
        assert qa_review_body_is_empty("NEEDS_REVISION\n___\n") is True
        assert _qa_line_is_substantive("0") is False
        assert _qa_line_is_substantive("1234567890") is False

    @pytest.mark.parametrize(
        "reason",
        ["PySide6 합의 위반", "Qt5 잔존", "OAuth2 미구현", "SHA256 미사용", "Python3 호환성 문제"],
    )
    def test_R3_4_5_digit_bearing_reason_preserved(self, reason: str) -> None:
        """숫자 포함 기술명(PySide6 등)을 괄호 사유로 단 줄은 verdict-only 로 *오흡수되지 않고* 실 내용으로 보존.

        핵심 R3#4/#5: 카운트괄호 흡수가 KEY=NUM 문법으로 좁혀져 산문 괄호('PySide6 위반')는 보존됨.
        구조 헤더 없는 raw 산출(컴플라이언스/보안 등)에서 이 줄이 유일 본문이어도 빈 본문으로 안 덮어씀.
        """
        line = f"NEEDS_REVISION ({reason})"
        assert _qa_line_is_substantive(line) is True
        # §3/§4 헤더 없는 raw 형태 — 실 사유 줄이 보존되어 빈 본문 아님
        assert qa_review_body_is_empty(f"Final Answer: NEEDS_REVISION\n{line}\n") is False
        # §3 에 정상 배치되면 당연히 보존
        assert qa_review_body_is_empty(_md(s3=f"- {line}")) is False

    def test_R3_4_5_severity_count_paren_still_absorbed(self) -> None:
        """반대로 순수 심각도 카운트 괄호는 여전히 verdict-only 로 흡수(빈 본문 위장 차단)."""
        assert qa_review_body_is_empty("NEEDS_REVISION (HIGH=1, MEDIUM=2)") is True

    def test_R3_6_R4_5_ambiguous_with_approved_is_residual(self) -> None:
        """R3#6→R4#5 정제: verdict 에 APPROVED 토큰이 *함께* 있으면(모호) 게이트하지 않는다.

        정상 승인을 NEEDS_REVISION 으로 뒤집는 R4#5 회귀가 더 위험하므로, APPROVED 흔적이 있는
        모호 verdict + 빈 본문은 의도된 잔여(generation validator·convergence judge 보조). 단,
        APPROVED 흔적이 *없는* 순수 NEEDS_REVISION 모호 + 빈 본문은 여전히 게이트한다(대조군).
        """
        # APPROVED 흔적 있는 모호 → 비대상(잔여)
        assert qa_review_body_is_empty(_md(verdict="NEEDS_REVISION (이전 APPROVED 회귀)")) is False
        # APPROVED 흔적 없는 순수 NR 모호 → 게이트
        assert qa_review_body_is_empty(_md(verdict="NEEDS_REVISION 회귀건")) is True

    def test_R3_9_last_final_answer_wins(self) -> None:
        """본문 앞쪽 인용된 'Final Answer: APPROVED' 가 아니라 말미의 진짜 verdict 를 채택."""
        text = "## 보고서\n예시 Final Answer: APPROVED 형식\n### 3\n- main.py 깨짐\nFinal Answer: NEEDS_REVISION\n"
        assert _qa_verdict_of(text) == "NEEDS_REVISION"

    def test_R3_12_status_table_only_is_empty(self) -> None:
        """§2 항목별 점검(상태표)만 채우고 §3/§4 가 비면 빈 본문(게이트가 §3/§4 만 계수)."""
        assert qa_review_body_is_empty(_md(s1="요약", s2="| 1 | 타입 | OK |", s5="없음")) is True

    def test_R3_12_real_issue_in_s3_not_empty(self) -> None:
        """대조군: §3 에 실 이슈가 있으면 §2 와 무관하게 본문 있음."""
        assert qa_review_body_is_empty(_md(s2="| 1 | 타입 | OK |", s3="- app.py:12 타입 누락")) is False

    def test_R3_14_verdict_in_table_cell_is_empty(self) -> None:
        """표 셀에 감싼 verdict(`| NEEDS_REVISION |`)도 verdict 선언으로 보아 빈 본문."""
        assert qa_review_body_is_empty("NEEDS_REVISION\n| NEEDS_REVISION |\n") is True

    def test_R3_10_dead_symbols_removed(self) -> None:
        """삭제 대상 데드/취약 심볼이 모듈에서 제거됨(NameError 회귀 방지)."""
        import src.workflows._schemas as sc
        for sym in ["_QA_VERDICT_TOKENS", "_QA_ACTIONABLE_RE", "_QA_NO_ISSUE_RE", "_QA_VERDICT_LINE_RE", "_QA_MIN_BODY_CHARS"]:
            assert not hasattr(sc, sym), sym
