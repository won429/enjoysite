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
# 🔍 네이버 데이터 구조에서 경기 무조건 찾아내기 (부분 일치 허용)
# ==========================================
def find_game_data(data, match_id):
    if isinstance(data, dict):
        game_id = str(data.get('gameId', ''))
        if not game_id:
            game_id = str(data.get('id', ''))
            
        # 💡 핵심: 네이버가 20260324HTSS0 까지만 쓰더라도 알아서 매칭되게 처리!
        if game_id and len(game_id) >= 8 and (match_id in game_id or game_id in match_id):
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
# 🚀 2. 탐지 레이더 크롤링 🚀
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 경기 데이터 수집 중...")
    if len(naver_match_id) < 8:
        return None
        
    date_str = f"{naver_match_id[:4]}-{naver_match_id[4:6]}-{naver_match_id[6:8]}"
    
    # KBO 목록부터 단일 경기 페이지까지 전부 찌름
    api_urls = [
        f"https://api-gw.sports.naver.com/schedule/games/list?categoryId=kbo&date={date_str}",
        f"https://api-gw.sports.naver.com/schedule/games/list?categoryId=kbaseball&date={date_str}",
        f"https://api-gw.sports.naver.com/sports/api/game/{naver_match_id}/basic",
        f"https://m.sports.naver.com/game/{naver_match_id}/record"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*"
    }
    
    available_ids = set() # 훔쳐올 실제 ID 보관함
    
    for url in api_urls:
        try:
            print(f"👉 탐색 경로: {url[:65]}...")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200: continue
                
            data_list = []
            content_type = response.headers.get("Content-Type", "")
            
            if "application/json" in content_type:
                try: data_list.append(response.json())
                except: pass
            else:
                # API가 안되면 HTML 안에 숨겨진 JSON 덩어리들을 정규식으로 뜯어냄
                soup = BeautifulSoup(response.text, 'html.parser')
                for script in soup.find_all('script'):
                    if script.string and '{' in script.string:
                        match = re.search(r'(\{.*\})', script.string, re.DOTALL)
                        if match:
                            try: data_list.append(json.loads(match.group(1)))
                            except: pass
            
            for data in data_list:
                # (스파이 기능) 이 날짜에 존재하는 모든 경기 ID를 수집해둠
                def collect_ids(d):
                    if isinstance(d, dict):
                        gid = str(d.get('gameId', '')) or str(d.get('id', ''))
                        if gid and len(gid) >= 10: available_ids.add(gid)
                        for v in d.values(): collect_ids(v)
                    elif isinstance(d, list):
                        for i in d: collect_ids(i)
                collect_ids(data)
                
                target_game = find_game_data(data, naver_match_id)
                
                if target_game:
                    print("✅ 타겟 데이터 블록 발견!")
                    
                    # 데이터 파싱 (이름이 어떻게 바뀌든 추출)
                    game_status = target_game.get('gameStatusName') or target_game.get('statusCodeName') or target_game.get('statusInfo', {}).get('statusName', '경기전')
                    
                    away_score = target_game.get('awayScore')
                    if away_score is None: away_score = target_game.get('awayTeamScore')
                    if away_score is None: away_score = target_game.get('awayTeam', {}).get('score', 0)
                    
                    home_score = target_game.get('homeScore')
                    if home_score is None: home_score = target_game.get('homeTeamScore')
                    if home_score is None: home_score = target_game.get('homeTeam', {}).get('score', 0)
                    
                    away_pitcher = target_game.get('awayStarterName') or target_game.get('awayPitcherName') or target_game.get('awayTeam', {}).get('starter', '미정')
                    home_pitcher = target_game.get('homeStarterName') or target_game.get('homePitcherName') or target_game.get('homeTeam', {}).get('starter', '미정')
                    
                    print(f"✅ 파싱 성공!: [{game_status}] {away_score}:{home_score}")
                    
                    return {
                        "gameStatus": game_status,
                        "awayScore": int(away_score) if away_score else 0,
                        "homeScore": int(home_score) if home_score else 0,
                        "awayPitcher": away_pitcher,
                        "homePitcher": home_pitcher,
                        "lastUpdated": firestore.SERVER_TIMESTAMP
                    }
        except Exception as e:
            continue

    print("❌ 네이버에서 데이터를 찾지 못했습니다.")
    if available_ids:
        print(f"💡 [진단 결과] 이 날짜({date_str})에 네이버에 존재하는 실제 경기 ID들은 다음과 같습니다:")
        print(f"👉 {list(available_ids)}")
        print("만약 위 목록에 있다면, 맨 아랫줄의 naver_match_id 값을 위 목록에 있는 걸로 복사해서 바꿔주세요!")
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
