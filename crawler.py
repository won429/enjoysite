import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import requests
from bs4 import BeautifulSoup
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
# 🚀 2. "네이버 3중 우회 + 오늘 날짜 자동" 크롤러 🚀
# ==========================================
def fetch_todays_games():
    # 💡 1. 한국 시간 기준으로 오늘 날짜 가져오기 (YYYY-MM-DD 형식)
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    date_dash = today.strftime('%Y-%m-%d')
    print(f"\n📅 [자동 실행] 오늘 날짜({date_dash}) KBO 일정을 수집합니다...")

    # 💡 2. 봇 차단을 막기 위한 철저한 위장 + 3개의 예비 경로 준비
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/json,text/plain,*/*",
        "Referer": "https://m.sports.naver.com/"
    }

    urls = [
        f"https://api-gw.sports.naver.com/schedule/games/list?categoryId=kbaseball&date={date_dash}",
        f"https://api-gw.sports.naver.com/schedule/games?sports=kbaseball&date={date_dash}",
        f"https://m.sports.naver.com/kbaseball/schedule/index?date={date_dash}" # 최후의 보루 (HTML 강제 스크래핑)
    ]

    games_list = []

    # 복잡한 데이터 속에서 '야구 경기' 덩어리만 쏙쏙 골라내는 함수
    def extract_games(obj):
        if isinstance(obj, dict):
            game_id = obj.get('gameId') or obj.get('id')
            # 'awayTeam' 이라는 글자가 포함된 블록은 무조건 야구 경기 데이터임!
            if game_id and ('awayTeam' in obj or 'awayTeamName' in obj) and ('homeTeam' in obj or 'homeTeamName' in obj):
                # 중복 저장 방지
                if not any(g.get('gameId') == game_id for g in games_list):
                    obj['gameId'] = game_id
                    games_list.append(obj)
                return 
            for v in obj.values():
                extract_games(v)
        elif isinstance(obj, list):
            for item in obj:
                extract_games(item)

    # 💡 3. 경로를 하나씩 찌르면서 뚫리는 곳에서 데이터를 탈취합니다.
    for url in urls:
        print(f"👉 접속 시도: {url[:60]}...")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f"   ㄴ 접속 차단됨 (HTTP {res.status_code}) - 다음 경로로 이동합니다.")
                continue

            res.encoding = 'utf-8'

            # 깔끔한 API로 응답이 왔을 때
            if "application/json" in res.headers.get("Content-Type", ""):
                extract_games(res.json())
            # HTML 웹사이트로 응답이 왔을 때 (최후의 보루)
            else:
                soup = BeautifulSoup(res.text, 'html.parser')
                for s in soup.find_all('script'):
                    if s.string and '{' in s.string and 'awayTeam' in s.string:
                        try:
                            start = s.string.find('{')
                            end = s.string.rfind('}')
                            if start != -1 and end != -1:
                                json_data = json.loads(s.string[start:end+1])
                                extract_games(json_data)
                        except:
                            pass

            # 경기를 하나라도 찾았다면 더 이상 다른 경로를 찌를 필요 없음!
            if len(games_list) > 0:
                print(f"   ㄴ ✅ 데이터 수집 대성공! 총 {len(games_list)}개의 경기를 발견했습니다.")
                break

        except Exception as e:
            print(f"   ㄴ 에러 발생: {e} - 다음 경로로 이동합니다.")
            continue

    # 💡 4. 파이어베이스에 1번 방부터 순서대로 밀어 넣기
    if not games_list:
        print(f"\n❌ {date_dash} 오늘은 예정된 경기가 없거나 데이터를 찾지 못했습니다.")
        return

    print("\n🔥 파이어베이스에 경기 기록 업데이트를 시작합니다...")
    match_id = 1
    for game in games_list:
        # 안전하게 이름 추출
        a_name = game.get('awayTeamName')
        if not a_name and isinstance(game.get('awayTeam'), dict): a_name = game['awayTeam'].get('name', '원정')
        h_name = game.get('homeTeamName')
        if not h_name and isinstance(game.get('homeTeam'), dict): h_name = game['homeTeam'].get('name', '홈')

        # 상태 및 점수 추출
        status = game.get('gameStatusName') or game.get('statusCodeName') or '경기전'
        
        a_score = game.get('awayTeamScore')
        if a_score is None and isinstance(game.get('awayTeam'), dict): a_score = game['awayTeam'].get('score', 0)
        
        h_score = game.get('homeTeamScore')
        if h_score is None and isinstance(game.get('homeTeam'), dict): h_score = game['homeTeam'].get('score', 0)

        # 투수 추출
        a_pitcher = game.get('awayStarterName')
        if not a_pitcher and isinstance(game.get('awayTeam'), dict): a_pitcher = game['awayTeam'].get('starterName', '미정')
        
        h_pitcher = game.get('homeStarterName')
        if not h_pitcher and isinstance(game.get('homeTeam'), dict): h_pitcher = game['homeTeam'].get('starterName', '미정')

        # 파이어베이스 전송
        payload = {
            "awayTeam": a_name,
            "homeTeam": h_name,
            "gameStatus": status,
            "awayScore": int(a_score) if a_score else 0,
            "homeScore": int(h_score) if h_score else 0,
            "awayPitcher": a_pitcher if a_pitcher else "미정",
            "homePitcher": h_pitcher if h_pitcher else "미정",
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }

        print(f"🚀 [방번호 {match_id}] {a_name} vs {h_name} -> {status} ({a_score}:{h_score})")
        db.collection('lineups').document(str(match_id)).set(payload, merge=True)
        match_id += 1

    print("\n🎉 개막전 데이터 파이어베이스 전송 완료! 앱에서 점수를 확인하세요!")

if __name__ == "__main__":
    fetch_todays_games()
