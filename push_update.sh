#!/bin/bash
# push_update.sh
# -------------------------------------------------------------
# Oracle Cloud(또는 다른 상시 서버)의 crontab에 등록해서 쓰는 스크립트.
# build_once.py로 data.json을 갱신하고, 실제로 내용이 바뀌었을 때만
# git commit & push 합니다. 모든 출력은 update.log에 남습니다.
#
# 설정 방법
#   1) 이 파일을 kiwoom-sector-monitor 저장소 루트에 저장
#   2) chmod +x push_update.sh
#   3) crontab -e 에 아래 한 줄 등록 (3분마다 실행 예시):
#        */3 * * * * /path/to/kiwoom-sector-monitor/push_update.sh
#      1분마다 원하면 */3 대신 * 로 바꾸면 됩니다.
#   4) 이 서버에서 git push가 비밀번호 없이 되도록 사전 설정 필요:
#      - SSH 배포키(권장): 저장소 Settings > Deploy keys 에 공개키 등록,
#        원격 주소를 git@github.com:... (https 아님) 형태로 설정
#      - 또는 Personal Access Token을 https 원격 주소에 미리 박아두기
#        (git remote set-url origin https://<TOKEN>@github.com/유저/저장소.git)
# -------------------------------------------------------------
set -uo pipefail

# 이 스크립트가 있는 디렉터리(=저장소 루트)로 이동
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

LOG_FILE="update.log"
TS() { date "+%Y-%m-%d %H:%M:%S"; }

{
  echo "[$(TS)] ---- 실행 시작 ----"

  # 1) 최신 데이터 받아오기
  if ! python3 build_once.py; then
    echo "[$(TS)] build_once.py 실패, 이번 회차는 건너뜀"
    exit 1
  fi

  # 2) data.json이 실제로 바뀌었는지 확인
  if git diff --quiet -- data.json && git diff --cached --quiet -- data.json; then
    echo "[$(TS)] 변경 없음, 커밋 생략"
    exit 0
  fi

  # 3) 바뀐 경우에만 커밋 & 푸시
  git add data.json
  git commit -m "auto: update data.json $(TS)" >/dev/null
  if git push origin HEAD; then
    echo "[$(TS)] 푸시 완료"
  else
    echo "[$(TS)] 푸시 실패 (네트워크/인증 문제일 수 있음)"
  fi

  echo "[$(TS)] ---- 실행 종료 ----"
} >> "$LOG_FILE" 2>&1
