import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import time
import requests
from bs4 import BeautifulSoup

# ==========================================
# 🔥 1. 파이어베이스(서버) 접속 권한 얻기 (깃허브 보안 패치 완!) 🔥
# ==========================================
# 깃허브에 파일을 올리는 대신, '환경 변수(Secrets)'라는 안전한 금고에 텍스트 형태로 숨겨둔 키를 꺼내옴!
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    # 깃허브 액션 환경: 환경 변수에서 JSON 텍스트를 불러와서 변환
    cred_dict = json.loads(firebase_secret)
    cred = credentials.Certificate(cred_dict)
    print("✅ 깃허브 안전 금고(Secrets)에서 파이어베이스 키 로드 완료!")
else:
    # 로컬(내 컴퓨터) 환경: 파일에서 불러오기 (이 파일은 절대 깃허브에 올리지 말 것!)
    cred = credentials.Certificate("my-firebase-key.json")
    print("✅ 로컬 파일에서 파이어베이스 키 로드 완료!")

firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🕷️ 2. 네이버 스포츠 크롤링 (진짜로 긁어오기!) 🕷️
# ==========================================
def fetch_naver_lineup(naver_match_id):
    print(f"[{naver_match_id}] 네이버 스포츠 접속 중...")
    url = f"https://m.sports.naver.com/game/{naver_match_id}/lineup"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    script_tag = soup.find('script', id='__NEXT_DATA__')
    if not script_tag:
        print("❌ 데이터를 찾을 수 없습니다.")
        return None
        
    try:
        data = json.loads(script_tag.string)
        game_info = data['props']['pageProps']['initialState']['home']['gameInfo']
        lineups = data['props']['pageProps']['initialState']['lineup']['lineup']
        
        away_pitcher = game_info.get('apName', '미정')
        home_pitcher = game_info.get('hpName', '미정')
        
        away_batters = [player['name'] for player in lineups.get('away', []) if player.get('batOrder')]
        home_batters = [player['name'] for player in lineups.get('home', []) if player.get('batOrder')]
        
        if not away_batters or not home_batters:
            print("⚠️ 아직 네이버에 라인업이 안 떴습니다!")
            return None
            
        print("✅ 네이버 선발 라인업 데이터 확보 완벽 성공!")
        return {
            "awayPitcher": away_pitcher,
            "homePitcher": home_pitcher,
            "awayLineup": away_batters,
            "homeLineup": home_batters
        }
    except Exception as e:
        print(f"❌ 데이터 파싱 에러: {e}")
        return None

# ==========================================
# 🚀 3. 파이어베이스에 데이터 밀어넣기 🚀
# ==========================================
def update_lineup_to_firebase(app_match_id, naver_match_id):
    print("\n====================================")
    lineup_data = fetch_naver_lineup(naver_match_id)
    
    if not lineup_data:
        print("⚠️ 업데이트 중단: 라인업 데이터가 없습니다.")
        return
        
    doc_ref = db.collection('lineups').document(str(app_match_id))
    doc_ref.set(lineup_data)
    
    print(f"🔥 파이어베이스(Firestore) 업로드 성공! (앱 경기 번호: {app_match_id})")
    print("====================================\n")

# ==========================================
# ⏱️ 4. 봇 실행부
# ==========================================
if __name__ == "__main__":
    # 테스트: 1번 경기 (내일 개막전! 경기 1~2시간 전에 실행되면 파이어베이스로 쏙 들어감)
    update_lineup_to_firebase(app_match_id=1, naver_match_id="20260328KTLG0")