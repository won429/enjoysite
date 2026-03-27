import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import requests
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
    # 뒤에 오타가 붙어있어도 핵심 13자리만 빼서 검사
    core_id = match_id[:13] if len(match_id) >= 13 else match_id
    
    if isinstance(data, dict):
        game_id = str(data.get('gameId', '')) or str(data.get('id', ''))
        
        if game_id and len(game_id) >= 8 and (core_id in game_id or game_id in core_id):
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
# 🚀 2. 웹페이지 강제 뜯어보기 크롤링 🚀
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 경기 데이터 수집 중...")
    if len(naver_match_id) < 8:
        return None
        
    date_str = f"{naver_match_id[:4]}-{naver_match_id[4:6]}-{naver_match_id[6:8]}"
    core_id = naver_match_id[:13]
    
    # 💡 API가 막혔을 때를 대비해, 사람처럼 '야구 일정 웹페이지'에 직접 접속합니다.
    api_urls = [
        f"https://m.sports.naver.com/kbaseball/schedule/index?date={date_str}",
        f"https://m.sports.naver.com/game/{core_id}/record",
        f"https://api-gw.sports.naver.com/schedule/games/list?categoryId=kbaseball&date={date_str}"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/json,text/plain,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9"
    }
    
    available_ids = set()
    
    for url in api_urls:
        try:
            print(f"👉 탐색 경로: {url[:65]}...")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200: continue
                
            data_list = []
            
            # HTML 페이지면 강제로 숨겨진 JSON 데이터를 파싱
            if "text/html" in response.headers.get("Content-Type", "") or "<html" in response.text[:100].lower():
                soup = BeautifulSoup(response.text, 'html.parser')
                script = soup.find('script', id='__NEXT_DATA__')
                if script and script.string:
                    try: data_list.append(json.loads(script.string))
                    except: pass
            else:
                try: data_list.append(response.json())
                except: pass
            
            for data in data_list:
                def collect_ids(d):
                    if isinstance(d, dict):
                        gid = str(d.get('gameId', '')) or str(d.get('id', ''))
                        if gid and len(gid) >= 10: available_ids.add(gid)
                        for v in d.values(): collect_ids(v)
                    elif isinstance(d, list):
                        for i in d: collect_ids(i)
                collect_ids(data)
                
                target_game = find_game_data(data, core_id)
                
                if target_game:
                    print("✅ 타겟 데이터 블록 발견!")
                    
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
    else:
        print(f"💡 [진단 결과] {date_str} 날짜에는 네이버에 등록된 야구 경기가 하나도 없습니다! (날짜나 연도를 확인해주세요)")
        
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
    # 💡 맨 뒷자리 '2026' 지우고 정상적인 13자리 네이버 ID로 수정했습니다.
    # 만약 2026년에 경기가 없다면, 연도를 2024년(20240324HTSS0)으로 바꿔서 테스트해보세요!
    update_live_data_to_firebase(app_match_id=99, naver_match_id="20260324HTSS0")
