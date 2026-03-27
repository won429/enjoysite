import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import re
from bs4 import BeautifulSoup

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
# 🔍 네이버 데이터 구조에서 경기 무조건 찾아내기
# ==========================================
def find_game_data(data, match_id):
    if isinstance(data, dict):
        game_id = str(data.get('gameId', '')) or str(data.get('id', ''))
        
        if game_id and (match_id in game_id or game_id in match_id):
            if any(k in data for k in ['gameStatusName', 'statusCodeName', 'awayTeam', 'homeTeam', 'awayScore']):
                return data
                
        for key, value in data.items():
            result = find_game_data(value, match_id)
            if result: return result
    elif isinstance(data, list):
        for item in data:
            result = find_game_data(item, match_id)
            if result: return result
    return None

def parse_target_game(target_game):
    """추출해낸 데이터 조각에서 안전하게 점수를 뽑아냅니다."""
    game_status = target_game.get('gameStatusName') or target_game.get('statusCodeName') or target_game.get('statusInfo', {}).get('statusName', '경기전')
    
    away_score = target_game.get('awayScore')
    if away_score is None: away_score = target_game.get('awayTeamScore')
    if away_score is None: away_score = target_game.get('awayTeam', {}).get('score', 0)
    
    home_score = target_game.get('homeScore')
    if home_score is None: home_score = target_game.get('homeTeamScore')
    if home_score is None: home_score = target_game.get('homeTeam', {}).get('score', 0)
    
    away_pitcher = target_game.get('awayStarterName') or target_game.get('awayPitcherName') or target_game.get('awayTeam', {}).get('starter', '미정')
    home_pitcher = target_game.get('homeStarterName') or target_game.get('homePitcherName') or target_game.get('homeTeam', {}).get('starter', '미정')
    
    print(f"🎉 최종 수집 점수: [{game_status}] AWAY {away_score} : {home_score} HOME")
    
    return {
        "gameStatus": game_status,
        "awayScore": int(away_score) if away_score else 0,
        "homeScore": int(home_score) if home_score else 0,
        "awayPitcher": away_pitcher,
        "homePitcher": home_pitcher,
        "lastUpdated": firestore.SERVER_TIMESTAMP
    }

# ==========================================
# 🚀 2. "한글 인코딩 + 궁극의 강제 추출" 크롤링 🚀
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 경기 데이터 수집 중...")
    if len(naver_match_id) < 8: return None
        
    date_str = f"{naver_match_id[:4]}-{naver_match_id[4:6]}-{naver_match_id[6:8]}"
    
    # 🔥 네이버 최신 API와 웹페이지 경로를 총동원합니다.
    api_urls = [
        f"https://api-gw.sports.naver.com/schedule/games?sports=kbaseball&date={date_str}",
        f"https://api-gw.sports.naver.com/game/{naver_match_id}",
        f"https://m.sports.naver.com/game/{naver_match_id}/record",
        f"https://m.sports.naver.com/kbaseball/schedule/index?date={date_str}"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/json,text/plain,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9"
    }
    
    for url in api_urls:
        try:
            print(f"👉 탐색 경로: {url[:65]}...")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200: 
                print(f"   ㄴ 접속 실패 (HTTP {response.status_code})")
                continue
                
            # 🔥 핵심: 글자가 깨지지 않도록 무조건 UTF-8 한글 번역 강제 적용!
            response.encoding = 'utf-8'
            html = response.text
            
            # 1. 깔끔한 JSON API로 접속 성공했을 때
            if "application/json" in response.headers.get("Content-Type", ""):
                try: 
                    target = find_game_data(response.json(), naver_match_id)
                    if target: return parse_target_game(target)
                except: pass
                
            # 2. 웹사이트(HTML)로 접속했을 때 -> 화면에 숨겨진 JSON 보물상자 찾기
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.title.string if soup.title else 'No Title'
            print(f"   ㄴ 접속 성공! 페이지 타이틀: [{title.strip()}]") # 이제 깨지지 않고 정상 출력됩니다!
            
            # HTML 안의 모든 <script> 태그를 뒤져서 경기 정보 덩어리를 훔쳐냅니다.
            for s in soup.find_all('script'):
                text = s.string if s.string else ""
                if naver_match_id in text and '{' in text:
                    start = text.find('{')
                    end = text.rfind('}')
                    if start != -1 and end != -1:
                        try:
                            data = json.loads(text[start:end+1])
                            target = find_game_data(data, naver_match_id)
                            if target: return parse_target_game(target)
                        except: pass
            
            # 3. 보물상자마저 없다면? -> 무식하게 글자 틈새에서 정규식으로 강제 추출
            away_m = re.search(r'(?:awayScore|awayTeamScore)["\']?\s*:\s*(\d+)', html)
            home_m = re.search(r'(?:homeScore|homeTeamScore)["\']?\s*:\s*(\d+)', html)
            status_m = re.search(r'(?:gameStatusName|statusCodeName)["\']?\s*:\s*["\']([^"\']+)["\']', html)
            
            if away_m and home_m and status_m:
                print("   ㄴ 🔥 HTML 글자 틈새에서 강제 추출 성공!")
                away_p = re.search(r'(?:awayStarterName|awayPitcherName)["\']?\s*:\s*["\']([^"\']+)["\']', html)
                home_p = re.search(r'(?:homeStarterName|homePitcherName)["\']?\s*:\s*["\']([^"\']+)["\']', html)
                return {
                    "gameStatus": status_m.group(1),
                    "awayScore": int(away_m.group(1)),
                    "homeScore": int(home_m.group(1)),
                    "awayPitcher": away_p.group(1) if away_p else "미정",
                    "homePitcher": home_p.group(1) if home_p else "미정",
                    "lastUpdated": firestore.SERVER_TIMESTAMP
                }
                
        except Exception as e:
            print(f"   ㄴ 에러 발생: {e}")
            continue

    print("❌ 모든 경로를 탐색했으나 데이터를 추출하지 못했습니다.")
    return None

def update_live_data_to_firebase(app_match_id, naver_match_id):
    live_data = fetch_naver_live_data(naver_match_id)
    if live_data:
        doc_ref = db.collection('lineups').document(str(app_match_id))
        doc_ref.set(live_data, merge=True)
        print(f"🚀 파이어베이스 업데이트 완료! (앱 매치 ID: {app_match_id})")
    else:
        print("⚠️ 수집된 데이터가 없어 파이어베이스 업데이트를 수행하지 않았습니다.")

if __name__ == "__main__":
    update_live_data_to_firebase(app_match_id=99, naver_match_id="20260324HTSS02026")
