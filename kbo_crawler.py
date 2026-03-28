import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import time
from bs4 import BeautifulSoup

# 파이어베이스 관리자 권한 연결 (serviceAccountKey.json 필요)
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

def fetch_and_update_kbo_scores():
    # 깃허브 서버에서도 무조건 한국 시간(KST)으로 맞춤
    kst_time = datetime.utcnow() + timedelta(hours=9)
    today_str = kst_time.strftime('%Y-%m-%d')
    print(f"\n[{kst_time.strftime('%H:%M:%S')}] mykbostats.com 데이터 수집 시작...")

    url = "https://mykbostats.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print("❌ 사이트 통신 오류:", e)
        return

    # mykbostats의 영어 팀명을 우리 앱의 한글 팀명으로 완벽하게 변환!
    team_map = {
        'KIA': 'KIA', 'SSG': 'SSG', 'KT': 'KT', 'LG': 'LG', 'LOTTE': '롯데',
        'SAMSUNG': '삼성', 'DOOSAN': '두산', 'NC': 'NC', 'KIWOOM': '키움', 'HANWHA': '한화'
    }

    # 파이어베이스(우리 앱)에서 오늘 일정 가져오기
    matches_ref = db.collection('matches').where('date', '==', today_str).stream()
    our_matches = {}
    for doc in matches_ref:
        match_data = doc.to_dict()
        team1_name = match_data['team1'].strip()
        our_matches[team1_name] = doc.id
        
    print(f"🔎 우리 앱에 등록된 오늘({today_str}) 어웨이 팀들: {list(our_matches.keys())}")

    if not our_matches:
        print("⚠️ 우리 앱에 오늘 날짜로 등록된 일정이 없습니다!")
        return

    found_games = False
    
    # HTML 파싱: mykbostats 사이트의 구조를 분석해 경기 행(tr 또는 특정 블록)을 찾습니다.
    # 범용적으로 텍스트 블록을 읽어 팀 이름이 들어간 줄을 판별합니다.
    games = soup.find_all('tr') 
    
    for game in games:
        text = game.get_text(separator=' ', strip=True).upper()
        
        # 텍스트에 두 팀의 이름이 모두 포함되어 있는지 확인
        for eng_away, kor_away in team_map.items():
            if eng_away in text:
                for eng_home, kor_home in team_map.items():
                    if eng_away != eng_home and eng_home in text:
                        # 둘 다 찾음 (하나의 경기 행렬로 인식)
                        found_games = True
                        
                        # 기본 점수 및 상태 설정
                        away_score, home_score = 0, 0
                        gameStatus = "경기전"
                        
                        # 점수 파싱 시도 (숫자가 텍스트에 포함되어 있는지)
                        numbers = [int(s) for s in text.split() if s.isdigit()]
                        if len(numbers) >= 2:
                            # 보통 어웨이 점수가 먼저 나옵니다.
                            away_score = numbers[0]
                            home_score = numbers[1]
                            gameStatus = "경기중" # 점수가 있으면 최소 경기중
                            
                        # 상태 텍스트 확인
                        if 'FINAL' in text or 'F/' in text:
                            gameStatus = "종료"
                        elif 'CANCEL' in text or 'POSTPONED' in text or 'RAIN' in text:
                            gameStatus = "취소"

                        # 우리 앱 데이터베이스에 최종 저장!
                        if kor_away in our_matches:
                            match_id = our_matches[kor_away]
                            db.collection('lineups').document(str(match_id)).set({
                                'gameStatus': gameStatus,
                                'awayScore': away_score,
                                'homeScore': home_score,
                                'awayPitcher': '-', # mykbostats 기본 크롤링에서는 투수 생략
                                'homePitcher': '-'
                            }, merge=True)
                            
                            print(f"    ✔️ 업데이트 성공! Match ID: {match_id} ({kor_away} {away_score}:{home_score} {kor_home} - {gameStatus})")
                            
                            # 중복 처리를 막기 위해 딕셔너리에서 제거
                            del our_matches[kor_away]

    if not found_games:
        print("⚠️ mykbostats.com 에서 오늘 경기 정보를 찾을 수 없습니다.")

# 프로그램이 깃허브 무료 서버(5분 주기)에 맞춰 1분마다 총 5번 갱신하고 깔끔하게 꺼지도록 세팅!
if __name__ == "__main__":
    print("🚀 로사의 KBO 실시간 점수 봇 가동 (mykbostats.com 버전)!")
    for _ in range(5):
        fetch_and_update_kbo_scores()
        time.sleep(60) # 60초 대기 후 다시 수집 (1분 갱신 마법)
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
