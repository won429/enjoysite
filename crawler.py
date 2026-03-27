import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import requests
from datetime import datetime, timezone, timedelta

# ==========================================
# 🔥 1. 파이어베이스 접속 🔥
# ==========================================
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    try:
        cred_dict = json.loads(firebase_secret)
        cred = credentials.Certificate(cred_dict)
        print("✅ 깃허브 Secrets에서 파이어베이스 키 로드 완료!")
    except Exception as e:
        print(f"🚨 [치명적 에러] 파이어베이스 키 인증 실패: {e}")
        exit(1)
else:
    print("🚨 [치명적 에러] 'FIREBASE_CREDENTIALS'를 찾지 못했습니다!")
    exit(1)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🚀 2. "오늘 날짜 자동 탐색" 인공지능 크롤러 (다음/카카오 전용) 🚀
# ==========================================
def fetch_todays_games():
    # 💡 1. 한국 시간 기준으로 '오늘'이 며칠인지 스스로 알아냅니다! (다음은 YYYYMMDD 형식 사용)
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime('%Y%m%d')
    print(f"\n📅 [자동 실행] 오늘 날짜({today_str}) KBO 일정을 다음(카카오)에서 수집합니다...")

    # 깔끔한 다음(카카오) KBO 일정 API 타격
    url = f"https://sports.daum.net/prx/castbox/api/sports/games.json?league=kbo&date={today_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            
            # API에서 오늘 열리는 모든 경기 데이터를 바로 빼옵니다.
            games_list = data.get('data', [])
            
            if not games_list:
                print(f"❌ {today_str} 오늘은 예정된 KBO 경기가 없습니다 (월요일 휴식 등).")
                return
            
            print(f"✅ 총 {len(games_list)}개의 경기를 찾았습니다! 파이어베이스에 입력을 시작합니다.\n")
            
            # 💡 2. 찾아낸 경기들을 1번부터 순서대로 파이어베이스에 밀어 넣습니다!
            match_id = 1
            for game in games_list:
                a_name = game.get('awayTeamName', '원정')
                h_name = game.get('homeTeamName', '홈')
                
                status = game.get('gameResult', '경기전')
                if status == "종료": 
                    status = "경기종료"  # 앱에 맞게 상태명 변경
                    
                a_score = game.get('awayScore', 0)
                h_score = game.get('homeScore', 0)
                
                a_pitcher = game.get('awayStarterName', '미정')
                if not a_pitcher: a_pitcher = '미정'
                
                h_pitcher = game.get('homeStarterName', '미정')
                if not h_pitcher: h_pitcher = '미정'
                
                # 파이어베이스 전송용 데이터 포장
                payload = {
                    "awayTeam": a_name,
                    "homeTeam": h_name,
                    "gameStatus": status,
                    "awayScore": int(a_score) if a_score else 0,
                    "homeScore": int(h_score) if h_score else 0,
                    "awayPitcher": a_pitcher,
                    "homePitcher": h_pitcher,
                    "lastUpdated": firestore.SERVER_TIMESTAMP
                }
                
                print(f"🚀 [매치 {match_id}] {a_name} vs {h_name} -> {status} ({a_score}:{h_score}) 업데이트 중...")
                db.collection('lineups').document(str(match_id)).set(payload, merge=True)
                
                match_id += 1
                
            print("\n🎉 오늘의 모든 경기 업데이트가 완벽하게 끝났습니다!")
            
        else:
            print(f"❌ 다음(카카오) API 접속 실패 (HTTP {res.status_code})")
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    # 아무것도 입력할 필요 없습니다. 봇이 알아서 날짜와 팀을 찾습니다!
    fetch_todays_games()
