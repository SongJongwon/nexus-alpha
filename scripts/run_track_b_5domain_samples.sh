#!/usr/bin/env bash
# PR #78 후속 — 5 도메인 sample 재검증 (PR #75 회귀 비교용).
#
# 각 도메인 실행 전후로 outputs 디렉터리 스냅샷을 찍어 *어떤* workflow_* 디렉터리가
# 그 도메인 결과인지 추적. 결과는 outputs/track_b_5domain_pr78/ 아래 정리.

set -e

cd "$(dirname "$0")/.."
RESULTS_DIR="outputs/track_b_5domain_pr78"
mkdir -p "$RESULTS_DIR"

run_domain() {
  local label="$1"
  local request="$2"
  local domain_dir="$RESULTS_DIR/$label"
  mkdir -p "$domain_dir"
  echo "==================================================================="
  echo "[$label] start at $(date +%H:%M:%S)"
  echo "request: $request"
  echo "==================================================================="

  # before snapshot
  ls outputs/workflow_* 2>/dev/null | sort > "$domain_dir/_before.txt" || true

  local start_ts=$(date +%s)
  set +e
  .venv/Scripts/python.exe scripts/run_e2e_10th_verification.py \
    --request "$request" \
    --enable-automate-branch \
    --max-retries 1 \
    > "$domain_dir/stdout.log" 2> "$domain_dir/stderr.log"
  local exit_code=$?
  set -e
  local end_ts=$(date +%s)
  local elapsed=$((end_ts - start_ts))

  # after snapshot — diff 가 새로 생긴 디렉터리
  ls outputs/workflow_* 2>/dev/null | sort > "$domain_dir/_after.txt" || true
  comm -13 "$domain_dir/_before.txt" "$domain_dir/_after.txt" > "$domain_dir/new_workflow_dirs.txt"

  echo "[$label] exit=$exit_code elapsed=${elapsed}s"
  echo "[$label] new workflow dirs:"
  cat "$domain_dir/new_workflow_dirs.txt" || true
  echo
}

run_domain "1_web_scraping"      "네이버 쇼핑 가격 크롤링 스크립트"
run_domain "2_api_integration"   "GitHub API 이슈 자동 생성 스크립트"
run_domain "3_desktop_automation" "Excel 자동 입력 RPA 스크립트"
run_domain "4_data_parser"       "한글 Excel 파일 파싱 스크립트"
run_domain "5_devops"            "FastAPI Docker 배포 파이프라인"

echo "ALL DONE at $(date +%H:%M:%S)"
