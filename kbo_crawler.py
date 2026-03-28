import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import time

# 파이어베이스 관리자 권한 연결 (serviceAccountKey.json 필요)
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

def fetch_and_update_kbo_scores():
    # 깃허브 서버(미국)에서도 무조건 한국 시간(KST)으로 작동하도록 시간 맞춤!
    kst_time = datetime.utcnow() + timedelta(hours=9)
    
    # 🔥 오늘과 내일 날짜를 배열로 만들어 두 번 연속으로 긁어오도록 설정! 🔥
    target_dates = [
        kst_time.strftime('%Y-%m-%d'),
        (kst_time + timedelta(days=1)).strftime('%Y-%m-%d')
    ]
    
    for target_date in target_dates:
        print(f"\n[{kst_time.strftime('%H:%M:%S')}] {target_date} KBO 실시간 데이터 수집 시작...")

        url = f"https://api-gw.sports.naver.com/schedule/games/kbo?date={target_date}"
        # 네이버 차단 방지용 신분증명(Referer)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://sports.naver.com/"
        }
        
        try:
            res = requests.get(url, headers=headers)
            data = res.json()
        except Exception as e:
            print(f"❌ 네이버 API 통신 오류 ({target_date}):", e)
            continue # 에러가 나도 멈추지 않고 다음 날짜로 넘어감

        # 강력한 안전 장치: 데이터가 비어있어도 뻗지 않고 스무스하게 패스!
        result_data = data.get('result', {})
        if not result_data or 'games' not in result_data or len(result_data['games']) == 0:
            print(f"⚠️ {target_date} 네이버 데이터를 불러올 수 없습니다. (이유: 네이버 서버에 해당 날짜 경기 데이터가 비어있음)")
            continue

        # 파이어베이스(우리 앱)에서 해당 날짜 일정을 가져옴
        matches_ref = db.collection('matches').where('date', '==', target_date).stream()
        
        our_matches = {}
        for doc in matches_ref:
            match_data = doc.to_dict()
            # 팀 이름을 대문자로 바꾸고 공백 제거해서 정확한 매칭 준비
            team1_name = match_data['team1'].upper().strip()
            our_matches[team1_name] = doc.id
            
        print(f"🔎 파이어베이스(우리 앱)에 등록된 {target_date} 어웨이 팀들: {list(our_matches.keys())}")

        # 네이버 데이터에서 점수, 라인업 정보 추출
        for game in result_data['games']:
            away_team = game.get('awayTeamName', '').upper().strip()
            home_team = game.get('homeTeamName', '').upper().strip()
            status = game.get('statusCode')
            
            # 네이버 상태 코드를 로사님 앱 상태로 변환
            gameStatus = "경기전"
            if status == "PLAY": gameStatus = "경기중"
            elif status == "RESULT": gameStatus = "종료"
            elif status == "CANCEL": gameStatus = "취소"
            
            away_score = game.get('awayTeamScore', 0)
            home_score = game.get('homeTeamScore', 0)
            
            away_pitcher = game.get('awayStarterName', '-')
            home_pitcher = game.get('homeStarterName', '-')

            # 네이버의 어웨이 팀이 우리 앱 일정에 있다면 실시간 점수와 투수 정보 덮어쓰기!
            if away_team in our_matches:
                match_id = our_matches[away_team]
                
                db.collection('lineups').document(str(match_id)).set({
                    'gameStatus': gameStatus,
                    'awayScore': away_score,
                    'homeScore': home_score,
                    'awayPitcher': away_pitcher,
                    'homePitcher': home_pitcher
                }, merge=True)
                
                print(f"    ✔️ 자동 갱신 성공! Match ID: {match_id} [{gameStatus}] {away_score}:{home_score}")
            else:
                print(f"    ❌ 패스: 앱 일정에 '{away_team}' 팀이 없습니다.")

# 프로그램이 깃허브 무료 서버(5분 주기)에 맞춰 1분마다 총 5번 갱신하고 깔끔하게 꺼지도록 세팅!
if __name__ == "__main__":
    print("🚀 로사의 KBO 실시간 점수 봇 가동!")
    for _ in range(5):
        fetch_and_update_kbo_scores()
        time.sleep(60) # 60초 대기 후 다시 수집 (1분 갱신 마법)
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
