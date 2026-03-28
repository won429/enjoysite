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
    print(f"\n[{kst_time.strftime('%H:%M:%S')}] KBO 실시간 데이터 수집 시작 ({today_str})")

    # 1. 파이어베이스(우리 앱)에서 오늘 일정 가져오기
    matches_ref = db.collection('matches').where('date', '==', today_str).stream()
    our_matches = {}
    for doc in matches_ref:
        match_data = doc.to_dict()
        team1_name = match_data['team1'].strip().upper()
        our_matches[team1_name] = doc.id
        
    print(f"🔎 우리 앱에 등록된 오늘({today_str}) 어웨이 팀들: {list(our_matches.keys())}")

    if not our_matches:
        print("⚠️ 우리 앱에 오늘 날짜로 등록된 일정이 없습니다!")
        return

    scraped_data = {}

    # 🔥 1차 코어: 네이버 스포츠 API (가장 빠르고 한국 시간에 정확함) 🔥
    try:
        url_naver = f"https://api-gw.sports.naver.com/schedule/games/kbo?date={today_str}"
        headers_naver = {"User-Agent": "Mozilla/5.0", "Referer": "https://sports.naver.com/"}
        res_naver = requests.get(url_naver, headers=headers_naver)
        data_naver = res_naver.json()
        
        if 'result' in data_naver and 'games' in data_naver['result']:
            for game in data_naver['result']['games']:
                away_team = game.get('awayTeamName', '').upper().strip()
                status_code = game.get('statusCode')
                
                st = "경기전"
                if status_code == "PLAY": st = "경기중"
                elif status_code == "RESULT": st = "종료"
                elif status_code == "CANCEL": st = "취소"
                
                scraped_data[away_team] = {
                    'status': st,
                    'awayScore': game.get('awayTeamScore', 0),
                    'homeScore': game.get('homeTeamScore', 0),
                    'awayPitcher': game.get('awayStarterName', '-'),
                    'homePitcher': game.get('homeStarterName', '-')
                }
    except Exception as e:
        pass # 에러가 나도 멈추지 않고 2차 코어로 넘어감

    # 🔥 2차 코어: mykbostats.com (네이버가 비었을 때를 대비한 보조 코어) 🔥
    if not scraped_data:
        try:
            url_mykbo = "https://mykbostats.com/"
            res_mykbo = requests.get(url_mykbo, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(res_mykbo.text, 'html.parser')
            
            team_map = {'KIA':'KIA', 'SSG':'SSG', 'KT':'KT', 'LG':'LG', 'LOTTE':'롯데', 'SAMSUNG':'삼성', 'DOOSAN':'두산', 'NC':'NC', 'KIWOOM':'키움', 'HANWHA':'한화'}
            
            lines = soup.get_text(separator='\n').split('\n')
            for line in lines:
                txt = line.strip().upper()
                found_teams = [kor for eng, kor in team_map.items() if eng in txt]
                
                if len(found_teams) >= 2:
                    away = found_teams[0]
                    st = "경기전"
                    if 'FINAL' in txt or 'F/' in txt: st = "종료"
                    elif 'CANCEL' in txt or 'POSTPONED' in txt or 'RAIN' in txt: st = "취소"
                    elif 'BOT ' in txt or 'TOP ' in txt or 'MID ' in txt: st = "경기중"
                    
                    nums = [int(s) for s in txt.split() if s.isdigit()]
                    away_score = nums[0] if len(nums) > 0 else 0
                    home_score = nums[1] if len(nums) > 1 else 0
                    
                    if len(nums) >= 2 and st == "경기전": st = "경기중"
                    
                    scraped_data[away] = {
                        'status': st,
                        'awayScore': away_score,
                        'homeScore': home_score,
                        'awayPitcher': '-',
                        'homePitcher': '-'
                    }
        except Exception as e:
            pass

    # 🔥 최종 방어 (무적 모터): 사이트가 아직 업데이트 안 된 새벽 시간대 무조건 처리! 🔥
    for app_away_team, match_id in our_matches.items():
        matched_key = None
        for scraped_team in scraped_data.keys():
            # 키움히어로즈, 키움 등 이름이 조금 달라도 매칭되도록 처리
            if app_away_team in scraped_team or scraped_team in app_away_team:
                matched_key = scraped_team
                break
        
        if matched_key:
            # 사이트에서 실시간 점수를 찾은 경우 (낮 경기 시간)
            data = scraped_data[matched_key]
            db.collection('lineups').document(str(match_id)).set({
                'gameStatus': data['status'],
                'awayScore': data['awayScore'],
                'homeScore': data['homeScore'],
                'awayPitcher': data['awayPitcher'],
                'homePitcher': data['homePitcher']
            }, merge=True)
            print(f"    ✔️ 실시간 연동 완료! Match ID: {match_id} [{data['status']}] {data['awayScore']}:{data['homeScore']}")
        else:
            # 사이트에 아직 점수판이 안 뜬 경우 (지금 같은 새벽 시간) -> 에러 내지 않고 강제 초기화!
            db.collection('lineups').document(str(match_id)).set({
                'gameStatus': '경기전',
                'awayScore': 0,
                'homeScore': 0
            }, merge=True)
            print(f"    ✔️ 사이트 대기중 (안전 초기화 완료)! Match ID: {match_id} [경기전] 0:0")

if __name__ == "__main__":
    print("🚀 로사의 KBO 무적의 듀얼 코어 봇 가동!")
    for _ in range(5):
        fetch_and_update_kbo_scores()
        time.sleep(60) # 60초 대기 후 다시 수집 (1분 갱신 마법)
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
