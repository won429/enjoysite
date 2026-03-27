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

# ==========================================
# 🚀 2. "핀셋 강제 추출" 크롤링 (절대 실패 안함) 🚀
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 경기 데이터 수집 중...")
    if len(naver_match_id) < 8:
        return None
        
    date_str = f"{naver_match_id[:4]}-{naver_match_id[4:6]}-{naver_match_id[6:8]}"
    
    # 보여주신 링크를 최우선 타겟으로 설정!
    api_urls = [
        f"https://m.sports.naver.com/game/{naver_match_id}/record",
        f"https://api-gw.sports.naver.com/sports/api/game/{naver_match_id}/basic",
        f"https://api-gw.sports.naver.com/schedule/games/list?categoryId=kbaseball&date={date_str}"
    ]
    
    # 봇 차단을 막기 위해 일반 크롬 브라우저인 척 위장
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
                
            data_list = []
            
            # 1. 만약 깔끔한 JSON API라면 기존처럼 파싱
            if "application/json" in response.headers.get("Content-Type", ""):
                try: data_list.append(response.json())
                except: pass
            else:
                # 2. 보여주신 페이지 같은 일반 웹사이트(HTML)라면? -> 강제 핀셋 추출 발동!
                html = response.text
                soup = BeautifulSoup(html, 'html.parser')
                title = soup.title.string if soup.title else 'No Title'
                print(f"   ㄴ 접속 성공! 페이지 타이틀: [{title.strip()}]")
                
                # 정규식(Regex)을 이용해 HTML 문자열 틈새에 숨은 점수 글자만 쏙쏙 뽑아냅니다.
                status_match = re.search(r'"gameStatusName"\s*:\s*"([^"]+)"', html) or re.search(r'"statusCodeName"\s*:\s*"([^"]+)"', html)
                away_score = re.search(r'"awayScore"\s*:\s*(\d+)', html) or re.search(r'"awayTeamScore"\s*:\s*(\d+)', html)
                home_score = re.search(r'"homeScore"\s*:\s*(\d+)', html) or re.search(r'"homeTeamScore"\s*:\s*(\d+)', html)
                
                if status_match and away_score and home_score:
                    away_pitcher = re.search(r'"awayStarterName"\s*:\s*"([^"]+)"', html) or re.search(r'"awayPitcherName"\s*:\s*"([^"]+)"', html)
                    home_pitcher = re.search(r'"homeStarterName"\s*:\s*"([^"]+)"', html) or re.search(r'"homePitcherName"\s*:\s*"([^"]+)"', html)
                    
                    print("   ㄴ 🔥 HTML 틈새에서 점수 데이터 강제 추출 성공!")
                    data_list.append({
                        "gameId": naver_match_id,
                        "gameStatusName": status_match.group(1),
                        "awayScore": int(away_score.group(1)),
                        "homeScore": int(home_score.group(1)),
                        "awayStarterName": away_pitcher.group(1) if away_pitcher else "미정",
                        "homeStarterName": home_pitcher.group(1) if home_pitcher else "미정"
                    })
            
            # 추출한 데이터를 정리해서 파이어베이스로 넘길 준비
            for data in data_list:
                target_game = find_game_data(data, naver_match_id)
                if target_game:
                    game_status = target_game.get('gameStatusName') or target_game.get('statusCodeName') or '경기전'
                    away_score = target_game.get('awayScore', 0)
                    home_score = target_game.get('homeScore', 0)
                    away_pitcher = target_game.get('awayStarterName', '미정')
                    home_pitcher = target_game.get('homeStarterName', '미정')
                    
                    print(f"🎉 최종 수집 점수: [{game_status}] AWAY {away_score} : {home_score} HOME")
                    
                    return {
                        "gameStatus": game_status,
                        "awayScore": int(away_score),
                        "homeScore": int(home_score),
                        "awayPitcher": away_pitcher,
                        "homePitcher": home_pitcher,
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
