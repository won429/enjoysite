import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import time
import requests
from bs4 import BeautifulSoup

# ==========================================
# 🔥 1. 파이어베이스(서버) 접속 권한 얻기 🔥
# ==========================================
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    # 깃허브 액션 환경: 안전 금고(Secrets)에서 키 로드
    cred_dict = json.loads(firebase_secret)
    cred = credentials.Certificate(cred_dict)
    print("✅ 깃허브 금고(Secrets)에서 파이어베이스 키 로드 완료!")
else:
    # 로컬 환경: 파일에서 키 로드 (절대 깃허브에 올리지 말 것!)
    cred = credentials.Certificate("my-firebase-key.json")
    print("✅ 로컬 파일에서 파이어베이스 키 로드 완료!")

firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🕷️ 2. 네이버 스포츠 크롤링 (실시간 점수 + 라인업) 🕷️
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 네이버 스포츠 실시간 데이터 접속 중...")
    url = f"https://m.sports.naver.com/game/{naver_match_id}/lineup"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    script_tag = soup.find('script', id='__NEXT_DATA__')
    if not script_tag:
        print("❌ 데이터를 찾을 수 없습니다. (경기 URL 오류 또는 페이지 구조 변경)")
        return None
        
    try:
        data = json.loads(script_tag.string)
        game_info = data['props']['pageProps']['initialState']['home']['gameInfo']
        lineups = data['props']['pageProps']['initialState']['lineup']['lineup']
        
        # 🔥 실시간 점수 및 진행 상태 (예: '경기전', '3회초', '종료') 🔥
        game_status = game_info.get('gameStatusName', '경기전')
        away_score = game_info.get('aScore', 0)
        home_score = game_info.get('hScore', 0)
        
        # 선발 투수
        away_pitcher = game_info.get('apName', '미정')
        home_pitcher = game_info.get('hpName', '미정')
        
        # 선발 타자 라인업
        away_batters = [player['name'] for player in lineups.get('away', []) if player.get('batOrder')]
        home_batters = [player['name'] for player in lineups.get('home', []) if player.get('batOrder')]
        
        if not away_batters or not home_batters:
            print(f"⚠️ [{game_status}] 라인업 미발표 상태입니다.")
            return None
            
        print(f"✅ 데이터 확보! [{game_status}] AWAY {away_score} : {home_score} HOME")
        return {
            "gameStatus": game_status,
            "awayScore": away_score,
            "homeScore": home_score,
            "awayPitcher": away_pitcher,
            "homePitcher": home_pitcher,
            "awayLineup": away_batters,
            "homeLineup": home_batters,
            "lastUpdated": firestore.SERVER_TIMESTAMP # 업데이트 시간 기록
        }
    except Exception as e:
        print(f"❌ 데이터 파싱 에러: {e}")
        return None

# ==========================================
# 🚀 3. 파이어베이스에 데이터 밀어넣기 🚀
# ==========================================
def update_live_data_to_firebase(app_match_id, naver_match_id):
    print("\n====================================")
    live_data = fetch_naver_live_data(naver_match_id)
    
    if not live_data:
        print("⚠️ 업데이트 중단: 크롤링한 데이터가 없습니다.")
        return
        
    # 파이어베이스 lineups 방에 덮어쓰기 (실시간 점수 갱신)
    doc_ref = db.collection('lineups').document(str(app_match_id))
    doc_ref.set(live_data)
    
    print(f"🔥 파이어베이스(Firestore) 업데이트 성공! (앱 경기 ID: {app_match_id})")
    print("====================================\n")

# ==========================================
# ⏱️ 4. 봇 실행부
# ==========================================
if __name__ == "__main__":
    # 💡 1번 경기 (3월 28일 KT vs LG)
    # 깃허브 봇이 15분마다 이 스크립트를 실행하면서 계속 점수를 업데이트 함!
    update_live_data_to_firebase(app_match_id=1, naver_match_id="20260328KTLG0")
