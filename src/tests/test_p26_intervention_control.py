# -*- coding: utf-8 -*-
"""v13 P26 — 개입 체크포인트 카운트다운을 사람이 통제(pause/resume/＋연장/타임아웃 필드) 회귀 test.

목표(개입 ON 한정): codegen 직전 체크포인트의 카운트다운을 사람이 통제 — 일시정지/재개(동결),
＋연장(N초 가산), 미리보기 열면 자동 일시정지(검토 중 만료 방지), GUI 타임아웃 필드. 개입 OFF 면 불변.

검증(하네스 통제 로직, 결정론 clock/sleeper/control_reader 주입):
  - paused → 카운트다운 *동결*(타임아웃 안 됨). paused fail-safe(무한 블록 금지).
  - added_sec(＋연장) → delta 만큼 잔여 가산(idempotent — 중복 적용 안 함).
  - 일시정지 아닐 때만 만료 → 기존 동작(피드백 없으면 진행) 유지.
  - 제어 파일 읽기/지속(삭제 안 함). 체크포인트 진입 시 stale 제어 클리어. 개입 OFF 회귀 0.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Optional

from src.workflows._intervention import (
    _CONTROL_FILENAME,
    _poll_intervention_file,
    _read_control_file,
    request_codegen_intervention,
)


def _write_feedback(f: Path, fb: str = "다크 테마로") -> None:
    f.write_text(json.dumps({"action": "inject", "feedback": fb}), encoding="utf-8")


class _Control:
    """결정론 control_reader — 호출별 control dict 시퀀스(+ 특정 호출에서 피드백 파일 기록 side-effect)."""

    def __init__(self, scripts: list, *, write_on: Optional[int] = None, file: Optional[Path] = None) -> None:
        self.scripts = scripts
        self.write_on = write_on
        self.file = file
        self.calls = 0

    def __call__(self) -> Optional[dict]:
        c = self.calls
        self.calls += 1
        if self.write_on is not None and c == self.write_on and self.file is not None:
            _write_feedback(self.file)
        return self.scripts[c] if c < len(self.scripts) else (self.scripts[-1] if self.scripts else None)


# =============================================================================
# 1. _read_control_file — 읽기/지속(삭제 안 함)/안전
# =============================================================================
class TestReadControl:
    def test_valid_dict(self, tmp_path: Path) -> None:
        p = tmp_path / _CONTROL_FILENAME
        p.write_text(json.dumps({"paused": True, "added_sec": 30}), encoding="utf-8")
        assert _read_control_file(p) == {"paused": True, "added_sec": 30}
        assert p.exists()  # *삭제 안 함* — 지속 상태

    def test_none_path(self) -> None:
        assert _read_control_file(None) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        assert _read_control_file(tmp_path / "nope.json") is None

    def test_bad_json(self, tmp_path: Path) -> None:
        p = tmp_path / "c.json"
        p.write_text("{not json", encoding="utf-8")
        assert _read_control_file(p) is None

    def test_non_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "c.json"
        p.write_text("[1,2]", encoding="utf-8")
        assert _read_control_file(p) is None


# =============================================================================
# 2. _poll_intervention_file — pause/resume/extend/timeout (결정론 주입)
# =============================================================================
class TestControllableWait:
    def test_pause_freezes_countdown(self, tmp_path: Path) -> None:
        """일시정지 중엔 카운트다운 동결 — timeout 을 한참 지나도 만료 안 됨. 그 사이 도착한 제출 잡음."""
        f = tmp_path / "i.json"
        # paused=True 지속, 3번째 reader 호출에서 피드백 파일 기록 → 다음 iter 에 잡힘.
        ctrl = _Control([{"paused": True}], write_on=3, file=f)
        out = _poll_intervention_file(
            f, timeout_sec=1, grace_sec=0, pause_budget_sec=100,
            sleeper=lambda _s: None, clock=itertools.count().__next__, control_reader=ctrl,
        )
        assert out == "다크 테마로"  # 동결 안 됐으면(=깨졌으면) timeout=1 에 만료돼 None

    def test_pause_failsafe_proceeds(self, tmp_path: Path) -> None:
        """fail-safe — 일시정지가 영영 안 풀려도(GUI 멈춤) pause_budget 초과 시 자동 진행(None)."""
        ctrl = _Control([{"paused": True}])  # 영원히 paused, 파일 없음
        out = _poll_intervention_file(
            tmp_path / "none.json", timeout_sec=1, grace_sec=0, pause_budget_sec=5,
            sleeper=lambda _s: None, clock=itertools.count().__next__, control_reader=ctrl,
        )
        assert out is None  # pause_budget(5) 초과 → 진행

    def test_resume_countdown_continues(self, tmp_path: Path) -> None:
        """재개 후 카운트다운 재개 → 만료 → None. (동결 동안 timeout 을 넘겼는데도 그땐 만료 안 됨.)"""
        # paused 10회(timeout=2 한참 넘김) → 이후 resume. 파일 없음.
        scripts = [{"paused": True}] * 10 + [{"paused": False}]
        ctrl = _Control(scripts)
        out = _poll_intervention_file(
            tmp_path / "none.json", timeout_sec=2, grace_sec=0, pause_budget_sec=1000,
            sleeper=lambda _s: None, clock=itertools.count().__next__, control_reader=ctrl,
        )
        assert out is None
        assert ctrl.calls > 10  # 동결 동안(>timeout=2) 만료 안 하고 살아있었음(재개 후 만료)

    def test_extend_adds_time_catches_late_submit(self, tmp_path: Path) -> None:
        """＋연장(added_sec) → 잔여 가산 → timeout 직후(연장 범위 내) 도착 제출을 잡음."""
        f = tmp_path / "i.json"
        # added_sec=50, 30번째 호출에서 파일 기록. timeout=1 이면 연장 없으면 진작 만료.
        ctrl = _Control([{"paused": False, "added_sec": 50}], write_on=30, file=f)
        out = _poll_intervention_file(
            f, timeout_sec=1, grace_sec=0, sleeper=lambda _s: None,
            clock=itertools.count().__next__, control_reader=ctrl,
        )
        assert out == "다크 테마로"

    def test_extend_idempotent(self, tmp_path: Path) -> None:
        """added_sec 누적값은 *delta* 만 가산 — 매 폴링 중복 가산되면 영영 안 끝남(회귀)."""
        f = tmp_path / "i.json"
        # added_sec=5 *고정*, 파일은 call 30 에 기록. idempotent 면 잔여=1+5=6 → call30 전에 만료(None).
        ctrl = _Control([{"paused": False, "added_sec": 5}], write_on=30, file=f)
        out = _poll_intervention_file(
            f, timeout_sec=1, grace_sec=0, sleeper=lambda _s: None,
            clock=itertools.count().__next__, control_reader=ctrl,
        )
        assert out is None  # 6초 잔여 < call30 → 만료(중복 가산이면 feedback 이 나옴 = 버그)

    def test_extend_regression_ignored(self, tmp_path: Path) -> None:
        """＋연장 누적값이 *되돌아가도*(연타 out-of-order/stale 기록) 이미 적용된 연장은 유실 0.

        프런트 직렬화 큐의 백스톱 — 하네스 단조 가드(added>applied 만 가산)가 작은 값을 무시해
        '한 번 늘어난 시간'을 지킨다. added 60 적용 후 30 으로 회귀해도 잔여=1+60 유지 → 늦은 제출 잡음.
        """
        f = tmp_path / "i.json"
        # 초반 added=60(적용) → 이후 added=30(회귀, 무시돼야). 파일은 call 40(잔여 61 내) 기록.
        scripts = [{"added_sec": 60}] * 3 + [{"added_sec": 30}]
        ctrl = _Control(scripts, write_on=40, file=f)
        out = _poll_intervention_file(
            f, timeout_sec=1, grace_sec=0, sleeper=lambda _s: None,
            clock=itertools.count().__next__, control_reader=ctrl,
        )
        assert out == "다크 테마로"  # 회귀로 시간이 깎였으면(=가드 깨짐) call40 전 만료 → None

    def test_extend_accumulates_across_clicks(self, tmp_path: Path) -> None:
        """＋연장 여러 번(added_sec 증가) → 누적 가산. 30+30=60 잔여로 call40 도착 잡음."""
        f = tmp_path / "i.json"
        scripts = [{"added_sec": 30}] * 5 + [{"added_sec": 60}]  # 두 번째 ＋연장
        ctrl = _Control(scripts, write_on=40, file=f)
        out = _poll_intervention_file(
            f, timeout_sec=1, grace_sec=0, sleeper=lambda _s: None,
            clock=itertools.count().__next__, control_reader=ctrl,
        )
        assert out == "다크 테마로"

    def test_normal_timeout_no_control(self, tmp_path: Path) -> None:
        """제어 없음(control_reader=None) → 기존대로 만료 시 None (회귀 0)."""
        out = _poll_intervention_file(
            tmp_path / "none.json", timeout_sec=1, grace_sec=0,
            sleeper=lambda _s: None, clock=itertools.count().__next__,
        )
        assert out is None

    def test_pause_then_submit_inject(self, tmp_path: Path) -> None:
        """일시정지 중 사용자가 피드백 제출 → 즉시 반환(동결과 무관하게 제출 우선)."""
        f = tmp_path / "i.json"
        ctrl = _Control([{"paused": True}], write_on=0, file=f)  # 첫 호출에 기록
        out = _poll_intervention_file(
            f, timeout_sec=1, grace_sec=0, pause_budget_sec=100,
            sleeper=lambda _s: None, clock=itertools.count().__next__, control_reader=ctrl,
        )
        assert out == "다크 테마로"


# =============================================================================
# 3. request_codegen_intervention — 제어 파일 배선 + 개입 OFF 불변
# =============================================================================
class TestRequestWiring:
    def test_off_does_not_touch_control(self, tmp_path: Path) -> None:
        """개입 OFF — 제어 파일에 손대지 않음(즉시 None, 회귀 0)."""
        stale = tmp_path / _CONTROL_FILENAME
        stale.write_text('{"paused": true}', encoding="utf-8")
        out = request_codegen_intervention("plan", intervene=False, run_root=tmp_path, file_poll=lambda: None)
        assert out is None
        assert stale.exists()  # OFF — 손대지 않음

    def test_on_clears_stale_control(self, tmp_path: Path) -> None:
        """개입 ON — 체크포인트 진입 시 직전 stale 제어 파일을 클리어(누수 방지)."""
        stale = tmp_path / _CONTROL_FILENAME
        stale.write_text('{"paused": true, "added_sec": 999}', encoding="utf-8")
        out = request_codegen_intervention("plan", intervene=True, run_root=tmp_path, file_poll=lambda: None)
        assert out is None
        assert not stale.exists()  # stale 제어 제거됨
