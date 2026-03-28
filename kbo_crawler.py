import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import time

cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

def fetch_and_update_kbo_scores():
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {today_str} KBO 실시간 데이터 수집 시작...")

    url = f"https://api-gw.sports.naver.com/schedule/games/kbo?date={today_str}"
    # 🔥 네이버 차단 방지용 신분증명(Referer) 추가 🔥
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://sports.naver.com/"
    }
    
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
    except Exception as e:
        print("네이버 API 통신 오류:", e)
        return

    # 🔥 강력한 안전 장치: 'result' 상자가 아예 없거나 비어있어도 뻗지 않고 부드럽게 패스! 🔥
    result_data = data.get('result', {})
    if not result_data or 'games' not in result_data or not result_data['games']:
        print("오늘 예정된 KBO 경기가 없거나 데이터를 불러올 수 없습니다.")
        return

    matches_ref = db.collection('matches').where('date', '==', today_str).stream()
    
    our_matches = {}
    for doc in matches_ref:
        match_data = doc.to_dict()
        our_matches[match_data['team1']] = doc.id

    for game in result_data['games']:
        away_team = game.get('awayTeamName')
        home_team = game.get('homeTeamName')
        status = game.get('statusCode')
        
        gameStatus = "경기전"
        if status == "PLAY": gameStatus = "경기중"
        elif status == "RESULT": gameStatus = "종료"
        elif status == "CANCEL": gameStatus = "취소"
        
        away_score = game.get('awayTeamScore', 0)
        home_score = game.get('homeTeamScore', 0)
        
        away_pitcher = game.get('awayStarterName', '-')
        home_pitcher = game.get('homeStarterName', '-')

        if away_team in our_matches:
            match_id = our_matches[away_team]
            
            db.collection('lineups').document(str(match_id)).set({
                'gameStatus': gameStatus,
                'awayScore': away_score,
                'homeScore': home_score,
                'awayPitcher': away_pitcher,
                'homePitcher': home_pitcher
            }, merge=True)
            
            print(f"✔️ 업데이트 완료: [{gameStatus}] {away_team} {away_score} : {home_score} {home_team} (Match ID: {match_id})")

if __name__ == "__main__":
    print("🚀 로사의 KBO 실시간 점수 봇 가동!")
    # 무한루프(while True) 대신 5번만 돌고 깔끔하게 종료
    for _ in range(5):
        fetch_and_update_kbo_scores()
        print("---------------------------------------")
        time.sleep(60) # 60초(1분) 대기 후 다시 수집
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
