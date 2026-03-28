import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import time

cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

def fetch_and_update_kbo_scores():
    kst_time = datetime.utcnow() + timedelta(hours=9)
    
    # 🔥 오늘과 내일 날짜를 배열로 만들어 두 번 연속으로 긁어오도록 수정! 🔥
    target_dates = [
        kst_time.strftime('%Y-%m-%d'),
        (kst_time + timedelta(days=1)).strftime('%Y-%m-%d')
    ]
    
    for target_date in target_dates:
        print(f"\n[{kst_time.strftime('%H:%M:%S')}] {target_date} KBO 실시간 데이터 수집 시작...")

        url = f"https://api-gw.sports.naver.com/schedule/games/kbo?date={target_date}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://sports.naver.com/"
        }
        
        try:
            res = requests.get(url, headers=headers)
            data = res.json()
        except Exception as e:
            print(f"❌ 네이버 API 통신 오류 ({target_date}):", e)
            continue # 에러나면 멈추지 않고 다음 날짜로 넘어감

        result_data = data.get('result', {})
        if not result_data or 'games' not in result_data or not result_data['games']:
            print(f"⚠️ {target_date} 네이버 데이터를 불러올 수 없습니다.")
            continue

        # 파이어베이스(우리 앱)에서는 해당 날짜 일정을 가져옵니다.
        matches_ref = db.collection('matches').where('date', '==', target_date).stream()
        
        our_matches = {}
        for doc in matches_ref:
            match_data = doc.to_dict()
            team1_name = match_data['team1'].upper().strip()
            our_matches[team1_name] = doc.id
            
        print(f"🔎 파이어베이스(우리 앱)에 등록된 {target_date} 어웨이 팀들: {list(our_matches.keys())}")

        for game in result_data['games']:
            away_team = game.get('awayTeamName', '').upper().strip()
            home_team = game.get('homeTeamName', '').upper().strip()
            status = game.get('statusCode')
            
            gameStatus = "경기전"
            if status == "PLAY": gameStatus = "경기중"
            elif status == "RESULT": gameStatus = "종료"
            elif status == "CANCEL": gameStatus = "취소"
            
            away_score = game.get('awayTeamScore', 0)
            home_score = game.get('homeTeamScore', 0)
            
            away_pitcher = game.get('awayStarterName', '-')
            home_pitcher = game.get('homeStarterName', '-')

            # 네이버의 어웨이 팀이 우리 앱 일정에 있다면 점수 강제 덮어쓰기!
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

if __name__ == "__main__":
    print("🚀 로사의 KBO 실시간 점수 봇 가동!")
    for _ in range(5):
        fetch_and_update_kbo_scores()
        time.sleep(60)
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
