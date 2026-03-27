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

# 💡 [새로 추가됨] 1~9번 타자 라인업을 훔쳐오는 기법
def get_lineup_deep(data, side):
    lineup = []
    def search(obj):
        nonlocal lineup
        if lineup: return
        if isinstance(obj, dict):
            # 네이버의 다양한 라인업 배열 이름들 대응
            for key in [f"{side}Lineup", f"{side}TeamLineup", f"{side}Batters", "lineup", "batters", "players"]:
                if key in obj and isinstance(obj[key], list) and len(obj[key]) > 0:
                    if isinstance(obj[key][0], dict):
                        # 딕셔너리 형태일 때 선수 이름만 쏙쏙 빼오기
                        temp = [p.get('name') or p.get('playerName') for p in obj[key] if isinstance(p, dict)]
                        temp = [t for t in temp if t] # 빈칸 제거
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
    return [p for p in lineup if p][:9] # 빈칸 제거 후 1~9번 타자만 리턴

# 💡 [새로 추가됨] 선발 투수만 콕 집어서 찾아내는 기법
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
# 🚀 2. "100% 화면 스크래핑 + 심층 침투" 메인 크롤러 🚀
# ==========================================
def fetch_todays_games():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    today_dash = today.strftime('%Y-%m-%d')
    today_prefix = today.strftime('%Y%m%d')
    
    print(f"\n📅 [1단계] 오늘({today_dash}) KBO 경기 껍데기(일정)를 찾습니다...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9"
    }

    urls = [
        "https://m.sports.naver.com/kbaseball",
        "https://m.sports.naver.com/kbaseball/schedule/index"
    ]

    games_list = []
    seen_ids = set()

    def extract_games_summary(obj):
        if isinstance(obj, dict):
            game_id = str(obj.get('gameId', '')) or str(obj.get('id', ''))
            if game_id and game_id.startswith(today_prefix):
                a_name = get_team_name(obj, "away")
                h_name = get_team_name(obj, "home")
                
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
                            "awayLineup": [], # 여기서부터 2단계에서 채울 예정입니다.
                            "homeLineup": []
                        })
                    return 
            for v in obj.values(): extract_games_summary(v)
        elif isinstance(obj, list):
            for item in obj: extract_games_summary(item)

    # 1차 스캔: 경기 일정 찾기
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')

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
                print(f"   ㄴ ✅ 총 {len(games_list)}개의 경기 일정을 찾았습니다!")
                break
        except: continue

    if not games_list:
        print(f"\n❌ {today_dash} 오늘은 예정된 KBO 경기가 없습니다.")
        return

    # 🔥 2차 스캔: 각 경기장(상세페이지)으로 쳐들어가서 타자/투수 라인업 털어오기! 🔥
    print("\n🕵️‍♂️ [2단계] 찾아낸 각 경기장에 직접 입장하여 라인업 명단을 탈취합니다...")
    for game in games_list:
        game_id = game['gameId']
        detail_url = f"https://m.sports.naver.com/game/{game_id}/record"
        print(f" 👉 [{game['awayTeam']} vs {game['homeTeam']}] 상세 페이지 진입 중...")
        
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
                
                # 혹시 일정표에서 선발 투수 이름을 못 가져왔다면 여기서 더 깊게 파서 추출
                if game['awayPitcher'] == "미정":
                    game['awayPitcher'] = get_pitcher_deep(detail_json, "away")
                if game['homePitcher'] == "미정":
                    game['homePitcher'] = get_pitcher_deep(detail_json, "home")
                    
                print(f"   ㄴ ✅ 라인업 확보! (AWAY: {len(game['awayLineup'])}명 / HOME: {len(game['homeLineup'])}명)")
            else:
                print("   ㄴ ⚠️ 상세 페이지에 데이터가 없습니다. (아직 라인업 발표 전일 수 있습니다)")
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
            "awayLineup": game['awayLineup'], # 🔥 훔쳐온 라인업 배열 전송!
            "homeLineup": game['homeLineup'], # 🔥 훔쳐온 라인업 배열 전송!
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }

        print(f"🚀 [방번호 {match_id}] {game['awayTeam']} vs {game['homeTeam']} 업로드 완료!")
        db.collection('lineups').document(str(match_id)).set(payload, merge=True)
        match_id += 1

    print("\n🎉 모든 스크래핑 및 파이어베이스 전송 대성공! 앱에서 라인업을 확인하세요!")

if __name__ == "__main__":
    fetch_todays_games()
