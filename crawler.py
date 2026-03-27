import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import time
import requests
from bs4 import BeautifulSoup

# ==========================================
# 🔥 1. 파이어베이스 접속 (에러 원인 추적기능 강화) 🔥
# ==========================================
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    try:
        cred_dict = json.loads(firebase_secret)
        cred = credentials.Certificate(cred_dict)
        print("✅ 깃허브 Secrets에서 파이어베이스 키 로드 완료!")
    except json.JSONDecodeError as e:
        print("🚨 [치명적 에러] 비밀금고(Secrets)에 넣은 텍스트가 올바른 JSON 형식이 아닙니다!")
        print("👉 원인: 복사할 때 괄호 { } 가 빠졌거나, 따옴표가 지워졌을 수 있습니다. 다시 복사해서 넣어보세요.")
        print(f"상세 에러: {e}")
        exit(1)
    except Exception as e:
        print(f"🚨 [치명적 에러] 파이어베이스 키 인증 실패: {e}")
        exit(1)
else:
    print("🚨 [치명적 에러] 비밀금고(Secrets)에서 'FIREBASE_CREDENTIALS'를 아예 찾지 못했습니다!")
    print("👉 원인: Secrets 이름을 잘못 적었거나(오타), 파일 로딩에 실패했습니다.")
    exit(1)

# 이미 초기화된 경우 방지
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🔍 JSON 구조에서 특정 경기 데이터 무조건 찾기 (재귀 탐색)
# ==========================================
def find_game_data(data, match_id):
    """복잡한 네이버 JSON 구조 안에서 match_id를 가진 딕셔너리를 무조건 찾아냅니다."""
    if isinstance(data, dict):
        if data.get('gameId') == match_id and 'gameStatusName' in data:
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
# 🕷️ 2. 네이버 스포츠 크롤링 (순수 데이터 모드) 🕷️
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 경기 데이터 수집 중...")
    url = f"https://m.sports.naver.com/game/{naver_match_id}/record"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            print("❌ 데이터를 찾지 못했습니다. (__NEXT_DATA__ 태그 없음)")
            return None
            
        data = json.loads(script_tag.string)
        target_game = find_game_data(data, naver_match_id)
        
        if not target_game:
            print(f"❌ 경기를 찾을 수 없습니다. (데이터 구조 내에 해당 ID 없음)")
            return None

        # 진짜 점수 및 상태 추출
        game_status = target_game.get('gameStatusName', '경기전')
        away_score = target_game.get('awayScore', target_game.get('awayTeamScore', 0))
        home_score = target_game.get('homeScore', target_game.get('homeTeamScore', 0))
        away_pitcher = target_game.get('awayStarterName', '미정')
        home_pitcher = target_game.get('homeStarterName', '미정')
        
        print(f"✅ 수집 완료: [{game_status}] {away_score}:{home_score}")
        
        return {
            "gameStatus": game_status,
            "awayScore": int(away_score) if away_score else 0,
            "homeScore": int(home_score) if home_score else 0,
            "awayPitcher": away_pitcher,
            "homePitcher": home_pitcher,
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }
    except Exception as e:
        print(f"❌ 크롤링 에러 발생: {e}")
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
    # 3월 24일 KIA vs 삼성 (시범경기 테스트)
    update_live_data_to_firebase(app_match_id=99, naver_match_id="20260324HTSS02026")
