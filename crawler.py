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
# 🚀 2. 다음(카카오) 스포츠 전용 크롤러 🚀
# ==========================================
def fetch_daum_live_data(match_id):
    print(f"[{match_id}] 다음(카카오) 스포츠에서 데이터 수집 시작...")
    
    # 회원님이 사용하는 ID(17자리든 뭐든)에서 앞부분 날짜와 팀 코드만 빼옵니다.
    if len(match_id) < 12:
        print("❌ 매치 ID 길이가 너무 짧습니다.")
        return None
        
    date_str = match_id[:8]
    away_code = match_id[8:10]
    home_code = match_id[10:12]

    # 네이버 알파벳 코드를 다음(카카오) 한글 팀명으로 번역
    TEAM_CODES = {
        'HT': 'KIA', 'SS': '삼성', 'LG': 'LG', 'OB': '두산', 'LT': '롯데',
        'SK': 'SSG', 'HH': '한화', 'KT': 'KT', 'NC': 'NC', 'WO': '키움'
    }
    
    away_name = TEAM_CODES.get(away_code, '')
    home_name = TEAM_CODES.get(home_code, '')
    
    # 깔끔한 다음(카카오) KBO 일정 API 타격
    url = f"https://sports.daum.net/prx/castbox/api/sports/games.json?league=kbo&date={date_str}"
    print(f"👉 접속 경로: {url}")
    
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            games = data.get('data', [])
            
            if not games:
                print(f"❌ {date_str} 날짜에 다음(카카오)에 등록된 경기가 없습니다.")
                return None
                
            for game in games:
                g_away = game.get('awayTeamName', '')
                g_home = game.get('homeTeamName', '')
                
                # 어웨이와 홈 팀 이름이 일치하면 바로 데이터 뽑기
                if (away_name and away_name in g_away) and (home_name and home_name in g_home):
                    game_status = game.get('gameResult', '경기전')
                    
                    # 상태값 통일 (다음은 '종료'로 오기 때문에 앱에 맞게 '경기종료'로 변환)
                    if game_status == "종료": 
                        game_status = "경기종료"
                        
                    a_score = game.get('awayScore', 0)
                    h_score = game.get('homeScore', 0)
                    
                    # 투수 정보 (다음 API에 있으면 넣고 없으면 미정 처리)
                    a_pitcher = game.get('awayStarterName', '미정')
                    if not a_pitcher: a_pitcher = '미정'
                    
                    h_pitcher = game.get('homeStarterName', '미정')
                    if not h_pitcher: h_pitcher = '미정'
                    
                    print(f"🎉 다음(카카오) 파싱 성공!: [{game_status}] AWAY {a_score} : {h_score} HOME")
                    
                    return {
                        "gameStatus": game_status,
                        "awayScore": int(a_score) if a_score else 0,
                        "homeScore": int(h_score) if h_score else 0,
                        "awayPitcher": a_pitcher,
                        "homePitcher": h_pitcher,
                        "lastUpdated": firestore.SERVER_TIMESTAMP
                    }
                    
            print(f"❌ '{away_name} vs {home_name}' 경기를 목록에서 찾지 못했습니다.")
        else:
            print(f"❌ 다음 서버 접속 실패 (HTTP {res.status_code})")
            
    except Exception as e:
        print(f"❌ 크롤링 에러 발생: {e}")
        
    return None

def update_live_data_to_firebase(app_match_id, match_id):
    live_data = fetch_daum_live_data(match_id)
    if live_data:
        doc_ref = db.collection('lineups').document(str(app_match_id))
        doc_ref.set(live_data, merge=True)
        print(f"🚀 파이어베이스 업데이트 완료! (앱 매치 ID: {app_match_id})")
    else:
        print("⚠️ 수집된 데이터가 없어 파이어베이스 업데이트를 수행하지 않았습니다.")

if __name__ == "__main__":
    # 💡 오늘 개막전 테스트용입니다. (원하시는 오늘 경기 ID로 바꿔서 테스트하셔도 됩니다!)
    update_live_data_to_firebase(app_match_id=99, match_id="20260324HTSS02026")
