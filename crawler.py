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
# ⚾ KBO 텍스트 판독 및 데이터 만능 추출기
# ==========================================
TEAM_MAP = {'HT': 'KIA', 'SS': '삼성', 'OB': '두산', 'LT': '롯데', 'SK': 'SSG', 'HH': '한화', 'WO': '키움', 'NC': 'NC', 'KT': 'KT', 'LG': 'LG'}
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
    name = game.get(f"{side}TeamName")
    if name and isinstance(name, str): return normalize_team(name)
    team_obj = game.get(f"{side}Team")
    if isinstance(team_obj, dict):
        name = team_obj.get("name") or team_obj.get("teamName")
        if name: return normalize_team(name)
    elif isinstance(team_obj, str): return normalize_team(team_obj)
    side_obj = game.get(side)
    if isinstance(side_obj, dict):
        name = side_obj.get("name") or side_obj.get("teamName")
        if name: return normalize_team(name)
    elif isinstance(side_obj, str): return normalize_team(side_obj)
    return ""

def get_score(game, side):
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

def get_pitcher_from_summary(game, side):
    p = game.get(f"{side}StarterName") or game.get(f"{side}PitcherName")
    if p and isinstance(p, str): return p
    team_obj = game.get(f"{side}Team")
    if isinstance(team_obj, dict):
        p = team_obj.get("starterName") or team_obj.get("pitcherName")
        if p: return str(p)
    return "미정"

def get_lineup_deep(data, side):
    lineup = []
    def search(obj):
        nonlocal lineup
        if lineup: return
        if isinstance(obj, dict):
            for key in [f"{side}Lineup", f"{side}TeamLineup", f"{side}Batters", "lineup", "batters", "players"]:
                if key in obj and isinstance(obj[key], list) and len(obj[key]) > 0:
                    if isinstance(obj[key][0], dict):
                        temp = [p.get('name') or p.get('playerName') for p in obj[key] if isinstance(p, dict)]
                        temp = [t for t in temp if t]
                        if len(temp) >= 9:
                            lineup = temp[:9]
                            return
                    elif isinstance(obj[key][0], str):
                        lineup = obj[key][:9]
                        return
            for v in obj.values(): search(v)
        elif isinstance(obj, list):
            for item in obj: search(item)
    search(data)
    return [p for p in lineup if p][:9]

def get_pitcher_deep(data, side):
    pitcher = "미정"
    def search(obj):
        nonlocal pitcher
        if pitcher != "미정": return
        if isinstance(obj, dict):
            for key in [f"{side}StarterName", f"{side}PitcherName", "starterName", "pitcherName", "starter"]:
                if key in obj and obj[key] and isinstance(obj[key], str):
                    pitcher = obj[key]
                    return
            for v in obj.values(): search(v)
        elif isinstance(obj, list):
            for item in obj: search(item)
    search(data)
    return pitcher

# ==========================================
# 🚀 2. "100% 화면 스크래핑 + 상세 침투" 메인 크롤러 🚀
# ==========================================
def fetch_todays_games():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    today_dash = today.strftime('%Y-%m-%d')
    today_prefix = today.strftime('%Y%m%d') # 🔥 무조건 이 날짜로 시작해야 합격!
    
    print(f"\n📅 [1단계] 100% 웹 스크래핑 모드 - 오늘({today_dash}) KBO 경기 일정을 화면에서 직접 뜯어옵니다...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9"
    }

    # 🔥 API는 전부 버렸습니다! 오직 일반 네이버 화면만 접속합니다.
    # 🔥 date 파라미터에 짝대기(-)를 빼고 붙여야 네이버가 2008년으로 안 튕깁니다.
    urls = [
        f"https://m.sports.naver.com/kbaseball/schedule/index?date={today_prefix}",
        "https://m.sports.naver.com/kbaseball"
    ]

    games_list = []
    seen_ids = set()

    def extract_games_summary(obj):
        if isinstance(obj, dict):
            game_id = str(obj.get('gameId', '')) or str(obj.get('id', ''))
            
            # 🔥 무조건 ID에 오늘 날짜(20260328)가 포함되어야 통과!
            if game_id and today_prefix in game_id:
                a_name = get_team_name(obj, "away")
                h_name = get_team_name(obj, "home")
                
                # 🔥 야구팀이 맞는지 한 번 더 검사!
                if a_name and h_name and (is_kbo_team(a_name) or is_kbo_team(h_name)):
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
                            "awayPitcher": get_pitcher_from_summary(obj, "away"),
                            "homePitcher": get_pitcher_from_summary(obj, "home"),
                            "awayLineup": [], 
                            "homeLineup": []
                        })
                    return 
            for v in obj.values(): extract_games_summary(v)
        elif isinstance(obj, list):
            for item in obj: extract_games_summary(item)

    # 1차 스캔: 경기 일정 찾기 (화면 통째로 뜯어오기)
    for url in urls:
        print(f"👉 웹페이지 접속 시도: {url[:60]}...")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            print(f"   ㄴ 화면 접속 성공! [타이틀: {soup.title.string if soup.title else '알 수 없음'}]")

            # 네이버 최신 화면 속 JSON 보물상자 직접 뜯기
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data and next_data.string:
                extract_games_summary(json.loads(next_data.string))
            else:
                for s in soup.find_all('script'):
                    if s.string and '{' in s.string and today_prefix in s.string:
                        try:
                            start = s.string.find('{')
                            end = s.string.rfind('}')
                            if start != -1 and end != -1:
                                extract_games_summary(json.loads(s.string[start:end+1]))
                        except: pass
            
            if len(games_list) > 0:
                print(f"   ㄴ ✅ 1단계 성공! 총 {len(games_list)}개의 오늘 야구 경기를 화면에서 찾았습니다!")
                break
        except Exception as e: 
            print(f"   ㄴ ⚠️ 탐색 에러: {e}")
            continue

    if not games_list:
        print(f"\n❌ {today_dash} 오늘은 화면상에 예정된 KBO 경기가 없습니다.")
        return

    # 🔥 2차 스캔: 찾아낸 경기 기록실 화면에 직접 들어가서 라인업 털어오기! 🔥
    print("\n🕵️‍♂️ [2단계] 웹 기록실에 각각 직접 입장하여 라인업을 훔쳐옵니다...")
    for game in games_list:
        game_id = game['gameId']
        # API 아님! 우리가 폰으로 누르는 그 기록실 사이트 주소입니다.
        detail_url = f"https://m.sports.naver.com/game/{game_id}/record"
        print(f" 👉 [{game['awayTeam']} vs {game['homeTeam']}] 상세 페이지 접속 중...")
        
        try:
            res = requests.get(detail_url, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            next_data = soup.find('script', id='__NEXT_DATA__')
            
            if next_data and next_data.string:
                detail_json = json.loads(next_data.string)
                
                # 1~9번 타자 라인업 추출
                game['awayLineup'] = get_lineup_deep(detail_json, "away")
                game['homeLineup'] = get_lineup_deep(detail_json, "home")
                
                if game['awayPitcher'] == "미정":
                    game['awayPitcher'] = get_pitcher_deep(detail_json, "away")
                if game['homePitcher'] == "미정":
                    game['homePitcher'] = get_pitcher_deep(detail_json, "home")
                    
                print(f"   ㄴ ✅ 라인업 확보! (AWAY: {len(game['awayLineup'])}명 / HOME: {len(game['homeLineup'])}명)")
            else:
                print("   ㄴ ⚠️ 상세 페이지에 데이터가 없습니다. (아직 라인업 발표 전이거나 기록실이 안 열림)")
        except Exception as e:
            print(f"   ㄴ ❌ 상세 페이지 접근 에러: {e}")

    # 3단계: 파이어베이스에 완성된 데이터 전송
    print("\n🔥 파이어베이스에 [라인업 포함] 전체 데이터를 업데이트합니다...")
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
            "awayLineup": game['awayLineup'], 
            "homeLineup": game['homeLineup'], 
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }

        print(f"🚀 [방번호 {match_id}] {game['awayTeam']} vs {game['homeTeam']} 업로드 완료!")
        db.collection('lineups').document(str(match_id)).set(payload, merge=True)
        match_id += 1

    print("\n🎉 화면 스크래핑 및 파이어베이스 전송 대성공! 앱에서 라인업을 확인하세요!")

if __name__ == "__main__":
    fetch_todays_games()
