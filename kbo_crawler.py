import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import time

# ==========================================
# 1. 파이어베이스 관리자 권한 연결
# (파이어베이스 설정에서 발급받은 비공개 키 파일 필요)
# ==========================================
# 다운받은 키 파일 이름을 'serviceAccountKey.json'으로 맞추고 같은 폴더에 넣으세요!
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

def fetch_and_update_kbo_scores():
    # 2. 오늘 날짜 구하기 (네이버 API에 요청할 포맷: YYYY-MM-DD)
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {today_str} KBO 실시간 데이터 수집 시작...")

    # 3. 네이버 스포츠 '숨겨진 직통 API' 호출 (HTML 화면을 긁는게 아니라서 100% 빠르고 정확함)
    url = f"https://api-gw.sports.naver.com/schedule/games/kbo?date={today_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
    except Exception as e:
        print("네이버 API 통신 오류:", e)
        return

    # 오늘 예정된 경기가 없으면 종료
    if 'games' not in data['result'] or not data['result']['games']:
        print("오늘 예정된 KBO 경기가 없습니다.")
        return

    # 4. 로사님의 파이어베이스 'matches' 컬렉션에서 '오늘 경기' 목록만 싹 가져오기
    # 이유: 파이어베이스에 저장된 match_id (1, 2, 3...)를 알아내기 위함
    matches_ref = db.collection('matches').where('date', '==', today_str).stream()
    
    our_matches = {}
    for doc in matches_ref:
        match_data = doc.to_dict()
        # 어웨이 팀 이름을 키값으로 파이어베이스 문서 ID를 저장
        our_matches[match_data['team1']] = doc.id

    # 5. 네이버에서 가져온 실시간 데이터를 파이어베이스에 매칭해서 밀어넣기
    for game in data['result']['games']:
        away_team = game.get('awayTeamName') # ex: 'KIA'
        home_team = game.get('homeTeamName') # ex: 'LG'
        status = game.get('statusCode')      # 네이버 상태 코드 (BEFORE, PLAY, RESULT, CANCEL)
        
        # 네이버 상태 코드를 로사님 앱 상태로 변환
        gameStatus = "경기전"
        if status == "PLAY": gameStatus = "경기중"
        elif status == "RESULT": gameStatus = "종료"
        elif status == "CANCEL": gameStatus = "취소"
        
        # 실시간 점수
        away_score = game.get('awayTeamScore', 0)
        home_score = game.get('homeTeamScore', 0)
        
        # 선발 투수
        away_pitcher = game.get('awayStarterName', '-')
        home_pitcher = game.get('homeStarterName', '-')

        # 우리 앱(파이어베이스)에 등록된 경기인지 확인 (팀 이름으로 매칭)
        if away_team in our_matches:
            match_id = our_matches[away_team]
            
            # 파이어베이스 'lineups' 컬렉션에 실시간 점수와 투수 정보 덮어쓰기!
            db.collection('lineups').document(str(match_id)).set({
                'gameStatus': gameStatus,
                'awayScore': away_score,
                'homeScore': home_score,
                'awayPitcher': away_pitcher,
                'homePitcher': home_pitcher
            }, merge=True)
            
            print(f"✔️ 업데이트 완료: [{gameStatus}] {away_team} {away_score} : {home_score} {home_team} (Match ID: {match_id})")

# 6. 프로그램이 꺼지지 않고 1분(60초)마다 자동으로 계속 갱신되게 무한 루프!
if __name__ == "__main__":
    print("🚀 로사의 KBO 실시간 점수 봇 가동!")
    while True:
        fetch_and_update_kbo_scores()
        print("---------------------------------------")
        time.sleep(60) # 60초 대기 후 다시 수집
