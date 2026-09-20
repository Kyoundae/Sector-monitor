"""
build_once.py
-------------------------------------------------------------
GitHub Actions에서 한 번만 실행되는 스크립트.
kiwoom_sector_watcher.py의 build_snapshot()을 재사용해서
data.json을 딱 1번 갱신하고 종료합니다. (로컬 실행용 watcher.py의
while True 반복 루프는 사용하지 않음)

환경변수 KIWOOM_APPKEY / KIWOOM_SECRETKEY는
GitHub Secrets → Actions에서 주입됩니다 (.env 파일 필요 없음).
-------------------------------------------------------------
"""
import json
from kiwoom_sector_watcher import build_snapshot, DATA_FILE, APPKEY, SECRETKEY


def main():
    if not APPKEY or not SECRETKEY:
        raise SystemExit("KIWOOM_APPKEY / KIWOOM_SECRETKEY 환경변수(GitHub Secrets)가 필요합니다.")

    snapshot = build_snapshot()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"[build_once] data.json 갱신 완료: {snapshot['updated_at']} "
          f"({len(snapshot['sectors'])}개 테마)")


if __name__ == "__main__":
    main()
