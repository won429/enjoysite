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
# ⚾ KBO 판독기 및 만능 이름/점수 추출기
# ==========================================
# 네이버가 영문 코드로 넘길 때를 대비해 번역 사전 추가
TEAM_MAP = {'HT': 'KIA', 'SS': '삼성', 'OB': '두산', 'LT': '롯데', 'SK': 'SSG', 'HH': '한화', 'WO': '키움'}
KBO_TEAMS = ["KIA", "기아", "삼성", "LG", "두산", "SSG", "NC", "롯데", "한화", "KT", "키움", "HT", "SS", "OB", "LT", "SK", "HH", "WO"]

def is_kbo_team(team_name):
    if not team_name: return False
    for kbo in KBO_TEAMS:
        if kbo.upper() in team_name.upper(): return True
    return False

def normalize_team(name):
    if not name: return "미상"
    name = str(name).strip()
    return TEAM_MAP.get(name.upper(), name)

def get_team_name(game, side):
    """어디에 숨어있든 홈/원정팀 이름을 기어코 찾아냅니다"""
    # 1. awayTeamName 형태
    name = game.get(f"{side}TeamName")
    if name and isinstance(name, str): return normalize_team(name)
    
    # 2. awayTeam: {name: "KIA"} 형태
    team_obj = game.get(f"{side}Team")
    if isinstance(team_obj, dict):
        name = team_obj.get("name") or team_obj.get("teamName")
        if name: return normalize_team(name)
    elif isinstance(team_obj, str): return normalize_team(team_obj)
        
    # 3. away: {name: "KIA"} 형태
    side_obj = game.get(side)
    if isinstance(side_obj, dict):
        name = side_obj.get("name") or side_obj.get("teamName")
        if name: return normalize_team(name)
    elif isinstance(side_obj, str): return normalize_team(side_obj)
        
    return ""

def get_score(game, side):
    """어디에 숨어있든 점수를 기어코 찾아냅니다"""
    score = game.get(f"{side}Score")
    if score is not None: return int(score)
    score = game.get(f"{side}TeamScore")
    if score is not None: return int(score)
    
    team_obj = game.get(f"{side}Team")
    if isinstance(team_obj, dict):
        score = team_obj.get("score")
        if score is not None: return int(score)
        
    side_obj = game.get(side)
    if isinstance(side_obj, dict):
        score = side_obj.get("score")
        if score is not None: return int(score)
    return 0

def get_pitcher(game, side):
    p = game.get(f"{side}StarterName") or game.get(f"{side}PitcherName")
    if p and isinstance(p, str): return p
    team_obj = game.get(f"{side}Team")
    if isinstance(team_obj, dict):
        p = team_obj.get("starterName") or team_obj.get("pitcherName")
        if p: return str(p)
    return "미정"

# ==========================================
# 🚀 3. "만능 파싱" KBO 자동 크롤러 🚀
# ==========================================
def fetch_todays_games():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    date_dash = today.strftime('%Y-%m-%d')
    print(f"\n📅 [자동 실행] 오늘 날짜({date_dash}) KBO 일정을 수집합니다...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json,text/html"
    }

    # 성공이 보장된 네이버 핵심 API 3대장
    urls = [
        f"https://api-gw.sports.naver.com/schedule/games?sports=kbaseball&date={date_dash}",
        f"https://api-gw.sports.naver.com/schedule/games/list?categoryId=kbaseball&date={date_dash}",
        f"https://m.sports.naver.com/kbaseball/schedule/index?date={date_dash}"
    ]

    games_list = []
    seen_ids = set() # 중복 수집 방지용

    def extract_games(obj):
        if isinstance(obj, dict):
            game_id = str(obj.get('gameId', '')) or str(obj.get('id', ''))
            
            # 🔥 핵심: 만능 추출기로 이름을 뽑아냅니다.
            a_name = get_team_name(obj, "away")
            h_name = get_team_name(obj, "home")
            
            # KBO 팀이 맞다면 무조건 통과!
            if game_id and a_name and h_name and (is_kbo_team(a_name) or is_kbo_team(h_name)):
                if game_id not in seen_ids:
                    seen_ids.add(game_id)
                    
                    status = str(obj.get('gameStatusName') or obj.get('statusCodeName') or obj.get('statusInfo', {}).get('statusName') or '경기전')
                    
                    games_list.append({
                        "gameId": game_id,
                        "awayTeam": a_name,
                        "homeTeam": h_name,
                        "gameStatus": status,
                        "awayScore": get_score(obj, "away"),
                        "homeScore": get_score(obj, "home"),
                        "awayPitcher": get_pitcher(obj, "away"),
                        "homePitcher": get_pitcher(obj, "home")
                    })
                return
            for v in obj.values(): extract_games(v)
        elif isinstance(obj, list):
            for item in obj: extract_games(item)

    for url in urls:
        print(f"👉 접속 시도: {url[:60]}...")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f"   ㄴ 접속 실패 (HTTP {res.status_code})")
                continue

            res.encoding = 'utf-8'

            if "application/json" in res.headers.get("Content-Type", ""):
                extract_games(res.json())
            else:
                soup = BeautifulSoup(res.text, 'html.parser')
                next_data = soup.find('script', id='__NEXT_DATA__')
                if next_data and next_data.string:
                    extract_games(json.loads(next_data.string))
                else:
                    for s in soup.find_all('script'):
                        if s.string and '{' in s.string and ('awayTeam' in s.string or 'away' in s.string):
                            try:
                                start = s.string.find('{')
                                end = s.string.rfind('}')
                                if start != -1 and end != -1:
                                    extract_games(json.loads(s.string[start:end+1]))
                            except: pass

            if len(games_list) > 0:
                print(f"   ㄴ ✅ 야구 데이터 수집 성공! 총 {len(games_list)}개의 KBO 경기를 발견했습니다.")
                break

        except Exception as e:
            print(f"   ㄴ 에러 발생: {e}")
            continue

    if not games_list:
        print(f"\n❌ {date_dash} 오늘은 예정된 KBO 경기가 없거나 데이터를 찾지 못했습니다.")
        return

    print("\n🔥 파이어베이스에 KBO 경기 기록 업데이트를 시작합니다...")
    match_id = 1
    for game in games_list:
        payload = {
            "awayTeam": game['awayTeam'],
            "homeTeam": game['homeTeam'],
            "gameStatus": game['gameStatus'],
            "awayScore": game['awayScore'],
            "homeScore": game['homeScore'],
            "awayPitcher": game['awayPitcher'],
            "homePitcher": game['homePitcher'],
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }

        print(f"🚀 [방번호 {match_id}] {game['awayTeam']} vs {game['homeTeam']} -> {game['gameStatus']} ({game['awayScore']}:{game['homeScore']})")
        db.collection('lineups').document(str(match_id)).set(payload, merge=True)
        match_id += 1

    print("\n🎉 개막전 데이터 파이어베이스 전송 완료! 앱에서 진짜 야구 점수를 확인하세요!")

if __name__ == "__main__":
    fetch_todays_games()
