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
# ⚾ KBO 텍스트 판독기 (축구/농구 필터링)
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

def get_pitcher(game, side):
    p = game.get(f"{side}StarterName") or game.get(f"{side}PitcherName")
    if p and isinstance(p, str): return p
    team_obj = game.get(f"{side}Team")
    if isinstance(team_obj, dict):
        p = team_obj.get("starterName") or team_obj.get("pitcherName")
        if p: return str(p)
    return "미정"

# ==========================================
# 🚀 2. "100% 화면 스크래핑" 무식하고 확실한 크롤러 🚀
# ==========================================
def fetch_todays_games():
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    today_dash = today.strftime('%Y-%m-%d')
    today_prefix = today.strftime('%Y%m%d') # 🔥 2008년 데이터는 이걸로 완벽하게 컷트합니다.
    
    print(f"\n📅 [100% 화면 스크래핑 모드] 오늘({today_dash}) 네이버 야구 화면의 글자를 통째로 읽어옵니다...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9"
    }

    # 💡 2008년으로 튕기는 버그를 막기 위해 '?date=...' 꼬리표를 아예 떼어버렸습니다.
    # 이렇게 들어가면 네이버가 알아서 '오늘' 화면을 보여줍니다.
    urls = [
        "https://m.sports.naver.com/kbaseball",                 # 1순위: 야구 메인 화면
        "https://m.sports.naver.com/kbaseball/schedule/index"   # 2순위: 야구 일정 화면
    ]

    games_list = []
    seen_ids = set()

    # 화면 구석구석 숨어있는 텍스트 덩어리를 까뒤집는 함수
    def extract_games(obj):
        if isinstance(obj, dict):
            game_id = str(obj.get('gameId', '')) or str(obj.get('id', ''))
            
            # 🔥 무조건 ID가 '20260328' 로 시작해야만 합격! (2008년 등 옛날 데이터 원천 차단)
            if game_id and game_id.startswith(today_prefix):
                a_name = get_team_name(obj, "away")
                h_name = get_team_name(obj, "home")
                
                # 🔥 축구/농구 버리고 KBO 야구팀만 합격!
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
                            "awayPitcher": get_pitcher(obj, "away"),
                            "homePitcher": get_pitcher(obj, "home")
                        })
                    return # 찾았으니 더 깊게 파지 않음
            for v in obj.values(): extract_games(v)
        elif isinstance(obj, list):
            for item in obj: extract_games(item)

    for url in urls:
        print(f"👉 앞문 접속 시도: {url}")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            
            # 여기서 네이버 웹페이지(HTML) 화면을 통째로 뜯어옵니다.
            soup = BeautifulSoup(res.text, 'html.parser')
            print(f"   ㄴ 화면 접속 성공! [타이틀: {soup.title.string if soup.title else '알 수 없음'}]")

            # 네이버 최신 화면은 __NEXT_DATA__ 라는 스크립트 상자에 글자를 숨겨둡니다.
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data and next_data.string:
                print("   ㄴ 🔥 화면 속 숨겨진 데이터 상자 발견! 텍스트 추출을 시작합니다.")
                extract_games(json.loads(next_data.string))
            else:
                # 혹시 상자가 없으면 화면에 있는 모든 스크립트 글자를 무식하게 다 뒤집니다.
                for s in soup.find_all('script'):
                    if s.string and '{' in s.string and today_prefix in s.string:
                        try:
                            start = s.string.find('{')
                            end = s.string.rfind('}')
                            if start != -1 and end != -1:
                                extract_games(json.loads(s.string[start:end+1]))
                        except: pass

            # 오늘 경기를 1개라도 뜯어냈다면 빙빙 돌지 않고 바로 종료!
            if len(games_list) > 0:
                print(f"   ㄴ ✅ 스크래핑 대성공! 총 {len(games_list)}개의 오늘 KBO 경기를 화면에서 긁어왔습니다.")
                break

        except Exception as e:
            print(f"   ㄴ 에러 발생: {e}")
            continue

    if not games_list:
        print(f"\n❌ {today_dash} 오늘은 화면에 예정된 KBO 경기가 없거나 점수판이 없습니다.")
        return

    print("\n🔥 파이어베이스에 스크래핑한 점수 업데이트를 시작합니다...")
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

    print("\n🎉 화면 스크래핑 및 파이어베이스 전송 완료! 앱에서 점수를 확인하세요!")

if __name__ == "__main__":
    fetch_todays_games()
