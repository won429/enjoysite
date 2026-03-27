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
# ⚾ KBO 10개 구단 판독기 (축구, 농구 난입 방지!)
# ==========================================
KBO_TEAMS = ["KIA", "기아", "삼성", "LG", "두산", "SSG", "NC", "롯데", "한화", "KT", "키움"]

def is_kbo_team(team_name):
    if not team_name: return False
    # 팀 이름에 KBO 구단 이름이 단 하나라도 포함되어 있으면 통과!
    for kbo in KBO_TEAMS:
        if kbo in team_name:
            return True
    return False

# ==========================================
# 🚀 2. "KBO 전용" 네이버 3중 우회 크롤러 🚀
# ==========================================
def fetch_todays_games():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    date_dash = today.strftime('%Y-%m-%d')
    print(f"\n📅 [자동 실행] 오늘 날짜({date_dash}) KBO 일정을 수집합니다...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/json,text/plain,*/*",
        "Referer": "https://m.sports.naver.com/"
    }

    # kbaseball 에서 kbo 로 ID를 변경하여 첫 번째 경로 404 에러도 수정했습니다.
    urls = [
        f"https://api-gw.sports.naver.com/schedule/games/list?categoryId=kbo&date={date_dash}",
        f"https://api-gw.sports.naver.com/schedule/games?sports=kbaseball&date={date_dash}",
        f"https://m.sports.naver.com/kbaseball/schedule/index?date={date_dash}"
    ]

    games_list = []

    def extract_games(obj):
        if isinstance(obj, dict):
            game_id = obj.get('gameId') or obj.get('id')
            if game_id:
                # 1. 일단 홈팀 원정팀 이름부터 뽑아봅니다.
                a_name = str(obj.get('awayTeamName') or obj.get('awayTeam', {}).get('name', ''))
                h_name = str(obj.get('homeTeamName') or obj.get('homeTeam', {}).get('name', ''))
                
                # 2. 뽑아낸 이름이 KBO 야구팀인지 철저하게 검사합니다. (축구팀 아웃!)
                if a_name and h_name and (is_kbo_team(a_name) or is_kbo_team(h_name)):
                    if not any(g.get('gameId') == game_id for g in games_list):
                        obj['gameId'] = game_id
                        games_list.append(obj)
                    return 
            for v in obj.values():
                extract_games(v)
        elif isinstance(obj, list):
            for item in obj:
                extract_games(item)

    for url in urls:
        print(f"👉 접속 시도: {url[:60]}...")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f"   ㄴ 접속 차단됨 (HTTP {res.status_code}) - 다음 경로로 이동합니다.")
                continue

            res.encoding = 'utf-8'

            if "application/json" in res.headers.get("Content-Type", ""):
                extract_games(res.json())
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

            if len(games_list) > 0:
                print(f"   ㄴ ✅ 야구 데이터 수집 성공! 총 {len(games_list)}개의 KBO 경기를 발견했습니다.")
                break

        except Exception as e:
            print(f"   ㄴ 에러 발생: {e} - 다음 경로로 이동합니다.")
            continue

    if not games_list:
        print(f"\n❌ {date_dash} 오늘은 예정된 KBO 경기가 없거나 데이터를 찾지 못했습니다.")
        return

    print("\n🔥 파이어베이스에 KBO 경기 기록 업데이트를 시작합니다...")
    match_id = 1
    for game in games_list:
        a_name = game.get('awayTeamName')
        if not a_name and isinstance(game.get('awayTeam'), dict): a_name = game['awayTeam'].get('name', '원정')
        h_name = game.get('homeTeamName')
        if not h_name and isinstance(game.get('homeTeam'), dict): h_name = game['homeTeam'].get('name', '홈')

        status = game.get('gameStatusName') or game.get('statusCodeName') or '경기전'
        
        a_score = game.get('awayTeamScore')
        if a_score is None and isinstance(game.get('awayTeam'), dict): a_score = game['awayTeam'].get('score', 0)
        
        h_score = game.get('homeTeamScore')
        if h_score is None and isinstance(game.get('homeTeam'), dict): h_score = game['homeTeam'].get('score', 0)

        a_pitcher = game.get('awayStarterName')
        if not a_pitcher and isinstance(game.get('awayTeam'), dict): a_pitcher = game['awayTeam'].get('starterName', '미정')
        
        h_pitcher = game.get('homeStarterName')
        if not h_pitcher and isinstance(game.get('homeTeam'), dict): h_pitcher = game['homeTeam'].get('starterName', '미정')

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

    print("\n🎉 개막전 데이터 파이어베이스 전송 완료! 앱에서 진짜 야구 점수를 확인하세요!")

if __name__ == "__main__":
    fetch_todays_games()
