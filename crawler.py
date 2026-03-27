import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import time
import requests
from bs4 import BeautifulSoup

# ==========================================
# 🔥 1. 파이어베이스 접속 🔥
# ==========================================
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    cred_dict = json.loads(firebase_secret)
    cred = credentials.Certificate(cred_dict)
    print("✅ 깃허브 Secrets에서 키 로드 완료!")
else:
    cred = credentials.Certificate("my-firebase-key.json")
    print("✅ 로컬 파일에서 키 로드 완료!")

# 이미 초기화된 경우 방지
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🕷️ 2. 네이버 스포츠 크롤링 (순수 데이터 모드) 🕷️
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 진짜 데이터만 수집 중...")
    # 시범경기나 기록 확인은 record 페이지 활용
    url = f"https://m.sports.naver.com/game/{naver_match_id}/record"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            print("❌ 데이터를 찾지 못했습니다.")
            return None
            
        data = json.loads(script_tag.string)
        schedule = data['props']['pageProps']['initialState']['schedule']['table']['dayGroupings']
        
        target_game = None
        for day in schedule:
            for game in day.get('games', []):
                if game.get('gameId') == naver_match_id:
                    target_game = game
                    break
        
        if not target_game:
            print(f"❌ 경기를 찾을 수 없습니다.")
            return None

        # 진짜 점수 및 상태만 추출 (가짜 데이터 일절 없음)
        game_status = target_game.get('gameStatusName', '경기전')
        away_score = target_game.get('awayScore', 0)
        home_score = target_game.get('homeScore', 0)
        
        print(f"✅ 수집 완료: [{game_status}] {away_score}:{home_score}")
        
        # 가짜 라인업 삭제됨 -> 실제 데이터 필드만 구성
        return {
            "gameStatus": game_status,
            "awayScore": int(away_score),
            "homeScore": int(home_score),
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        return None

def update_live_data_to_firebase(app_match_id, naver_match_id):
    live_data = fetch_naver_live_data(naver_match_id)
    if live_data:
        doc_ref = db.collection('lineups').document(str(app_match_id))
        doc_ref.set(live_data)
        print(f"🚀 파이어베이스 업데이트 완료! (ID: {app_match_id})")
    else:
        print("⚠️ 데이터가 없어 업데이트를 수행하지 않았습니다.")

if __name__ == "__main__":
    # 3월 24일 KIA vs 삼성 (진짜 데이터만 긁어오기)
    update_live_data_to_firebase(app_match_id=99, naver_match_id="20260324HTSS02026")
