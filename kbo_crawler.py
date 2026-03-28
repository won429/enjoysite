import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import time

cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

def fetch_and_update_kbo_scores():
    # 🔥 1. 무조건 한국 시간(KST)으로 고정! (깃허브 서버가 미국에 있어도 한국 날짜로 계산) 🔥
    kst_time = datetime.utcnow() + timedelta(hours=9)
    today_str = kst_time.strftime('%Y-%m-%d')
    print(f"\n[{kst_time.strftime('%H:%M:%S')}] {today_str} KBO 실시간 데이터 수집 시작...")

    url = f"https://api-gw.sports.naver.com/schedule/games/kbo?date={today_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://sports.naver.com/"
    }
    
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
    except Exception as e:
        print("❌ 네이버 API 통신 오류:", e)
        return

    result_data = data.get('result', {})
    if not result_data or 'games' not in result_data or not result_data['games']:
        print("⚠️ 오늘 예정된 KBO 경기가 없거나 네이버 데이터를 불러올 수 없습니다.")
        return

    # 파이어베이스에서 오늘 경기 가져오기
    matches_ref = db.collection('matches').where('date', '==', today_str).stream()
    
    our_matches = {}
    for doc in matches_ref:
        match_data = doc.to_dict()
        # 팀 이름을 대문자로 바꾸고 공백 제거해서 저장 (예: 'kt' -> 'KT')
        team1_name = match_data['team1'].upper().strip()
        our_matches[team1_name] = doc.id
        
    print(f"🔎 파이어베이스(우리 앱)에 등록된 오늘({today_str}) 어웨이 팀들: {list(our_matches.keys())}")

    if not our_matches:
        print("⚠️ 우리 앱에 오늘 날짜로 등록된 일정이 없습니다! (관리자 설정에서 일정을 추가했는지 확인하세요)")
        return

    # 네이버 데이터랑 매칭하기
    for game in result_data['games']:
        # 네이버 팀명도 대문자로 바꾸고 공백 제거
        away_team = game.get('awayTeamName', '').upper().strip()
        home_team = game.get('homeTeamName', '').upper().strip()
        status = game.get('statusCode')
        
        print(f"  -> 네이버 경기 발견: {away_team} vs {home_team} (상태: {status})")
        
        gameStatus = "경기전"
        if status == "PLAY": gameStatus = "경기중"
        elif status == "RESULT": gameStatus = "종료"
        elif status == "CANCEL": gameStatus = "취소"
        
        away_score = game.get('awayTeamScore', 0)
        home_score = game.get('homeTeamScore', 0)
        
        away_pitcher = game.get('awayStarterName', '-')
        home_pitcher = game.get('homeStarterName', '-')

        # 우리 앱에 네이버 어웨이팀 이름이 있는지 확인
        if away_team in our_matches:
            match_id = our_matches[away_team]
            
            db.collection('lineups').document(str(match_id)).set({
                'gameStatus': gameStatus,
                'awayScore': away_score,
                'homeScore': home_score,
                'awayPitcher': away_pitcher,
                'homePitcher': home_pitcher
            }, merge=True)
            
            print(f"    ✔️ 업데이트 성공! Match ID: {match_id} [{gameStatus}] {away_score}:{home_score}")
        else:
            print(f"    ❌ 매칭 실패: 우리 앱 일정에 '{away_team}' 팀이 없습니다.")

if __name__ == "__main__":
    print("🚀 로사의 KBO 실시간 점수 봇 가동!")
    for _ in range(5):
        fetch_and_update_kbo_scores()
        time.sleep(60)
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
