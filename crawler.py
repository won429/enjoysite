import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import requests

# ==========================================
# 🔥 1. 파이어베이스 접속 🔥
# ==========================================
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    try:
        cred_dict = json.loads(firebase_secret)
        cred = credentials.Certificate(cred_dict)
        print("✅ 깃허브 Secrets에서 파이어베이스 키 로드 완료!")
    except json.JSONDecodeError as e:
        print("🚨 [치명적 에러] 올바른 JSON 형식이 아닙니다!")
        exit(1)
    except Exception as e:
        print(f"🚨 [치명적 에러] 키 인증 실패: {e}")
        exit(1)
else:
    print("🚨 [치명적 에러] 'FIREBASE_CREDENTIALS'를 찾지 못했습니다!")
    exit(1)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🔍 JSON 구조에서 스마트하게 데이터 찾기
# ==========================================
def find_game_data(data, match_id):
    if isinstance(data, dict):
        if data.get('gameId') == match_id and ('gameStatusName' in data or 'statusCodeName' in data):
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
# 🚀 2. API 직접 호출 방식 (강력한 크롤링) 🚀
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 경기 데이터 수집 중...")
    
    # 💡 HTML 긁어오기가 막혔으니, 네이버 API 서버를 2중으로 찌릅니다!
    api_urls = [
        f"https://api-gw.sports.naver.com/sports/api/game/{naver_match_id}/basic",
        f"https://api-gw.sports.naver.com/schedule/games?sports=kbaseball&date={naver_match_id[:4]}-{naver_match_id[4:6]}-{naver_match_id[6:8]}"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://m.sports.naver.com",
        "Referer": f"https://m.sports.naver.com/game/{naver_match_id}/record"
    }
    
    for url in api_urls:
        try:
            print(f"👉 네이버 백엔드 API 호출 시도 중...")
            response = requests.get(url, headers=headers)
            
            if response.status_code != 200:
                continue
                
            data = response.json()
            target_game = find_game_data(data, naver_match_id)
            
            if target_game:
                # 상태 및 점수 추출 (네이버 내부 필드명 변경 대비)
                game_status = target_game.get('gameStatusName', target_game.get('statusCodeName', '경기전'))
                away_score = target_game.get('awayScore', target_game.get('awayTeamScore', 0))
                home_score = target_game.get('homeScore', target_game.get('homeTeamScore', 0))
                
                # 투수 이름
                away_pitcher = target_game.get('awayStarterName', target_game.get('awayPitcherName', '미정'))
                home_pitcher = target_game.get('homeStarterName', target_game.get('homePitcherName', '미정'))
                
                print(f"✅ 수집 성공!: [{game_status}] {away_score}:{home_score}")
                
                return {
                    "gameStatus": game_status,
                    "awayScore": int(away_score) if away_score else 0,
                    "homeScore": int(home_score) if home_score else 0,
                    "awayPitcher": away_pitcher,
                    "homePitcher": home_pitcher,
                    "lastUpdated": firestore.SERVER_TIMESTAMP
                }
        except Exception as e:
            print(f"⚠️ 에러 발생: {e}")
            continue

    print("❌ 모든 API 호출을 시도했으나 데이터를 찾지 못했습니다.")
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
