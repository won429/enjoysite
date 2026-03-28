import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import time
import json
import re

# 파이어베이스 관리자 권한 연결
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

def fetch_and_update_kbo_scores():
    # 무조건 한국 시간(KST)으로 맞춤
    kst_time = datetime.utcnow() + timedelta(hours=9)
    today_str = kst_time.strftime('%Y-%m-%d')
    date_code = kst_time.strftime('%Y%m%d') # 예: 20260329
    
    print(f"\n[{kst_time.strftime('%H:%M:%S')}] 다음(Daum) 스포츠 다이렉트 해킹 작전 시작 ({today_str})")

    # 1. 파이어베이스(우리 앱)에서 오늘 일정 가져오기
    matches_ref = db.collection('matches').where('date', '==', today_str).stream()
    our_matches = {}
    display_list = []
    
    for doc in matches_ref:
        match_data = doc.to_dict()
        t1 = match_data['team1'].strip().upper()
        t2 = match_data['team2'].strip().upper()
        our_matches[t1] = {'id': doc.id, 'home': t2}
        display_list.append(f"{t1} vs {t2}")

    if not our_matches:
        print("⚠️ 우리 앱에 오늘 날짜로 등록된 일정이 없습니다!")
        return
        
    print(f"🔎 우리 앱에 등록된 오늘 경기: {', '.join(display_list)}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://sports.daum.net/"
    }

    scraped_data = {}
    team_map = {'KIA':'KIA', 'SSG':'SSG', 'KT':'KT', 'LG':'LG', 'LOTTE':'롯데', 'SAMSUNG':'삼성', 'DOOSAN':'두산', 'NC':'NC', 'KIWOOM':'키움', 'HANWHA':'한화'}

    # 🔥 다음(Daum) 스포츠 숨겨진 데이터(JSON) 강제 추출 🔥
    daum_url = f"https://sports.daum.net/schedule/kbo?date={date_code}"
    try:
        res = requests.get(daum_url, headers=headers, timeout=10)
        
        # HTML 소스코드 안에 꽁꽁 숨어있는 window.__INITIAL_STATE__ = { ... }; 형태의 JSON 덩어리를 뜯어냅니다.
        match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});</script>', res.text, re.DOTALL)
        
        if match:
            json_text = match.group(1)
            daum_data = json.loads(json_text)
            
            # JSON 덩어리 안에서 경기 데이터를 모조리 찾아냅니다
            schedule_list = []
            def find_games(obj):
                if isinstance(obj, dict):
                    if ('homeName' in obj and 'awayName' in obj) or ('home' in obj and 'away' in obj and 'gameDate' in obj):
                        schedule_list.append(obj)
                    for k, v in obj.items():
                        find_games(v)
                elif isinstance(obj, list):
                    for item in obj:
                        find_games(item)
            
            find_games(daum_data)
            
            for game in schedule_list:
                # 다음(Daum)의 데이터 구조에 맞춰 팀명, 점수, 투수, 상태 추출
                eng_away = game.get('awayName') or game.get('away', {}).get('name', '')
                eng_home = game.get('homeName') or game.get('home', {}).get('name', '')
                
                if not eng_away or not eng_home: continue
                
                eng_away = eng_away.upper()
                eng_home = eng_home.upper()
                
                kor_away = team_map.get(eng_away, eng_away)
                kor_home = team_map.get(eng_home, eng_home)
                
                status_str = str(game.get('status', '')).upper()
                st = "경기전"
                if 'PLAY' in status_str or 'LIVE' in status_str or status_str == '2': st = "경기중"
                elif 'END' in status_str or 'RESULT' in status_str or status_str == '3': st = "종료"
                elif 'CANCEL' in status_str or status_str == '4': st = "취소"
                
                away_score = int(game.get('awayScore') or game.get('away', {}).get('score', 0) or 0)
                home_score = int(game.get('homeScore') or game.get('home', {}).get('score', 0) or 0)
                
                if st == "경기전" and (away_score > 0 or home_score > 0):
                    st = "경기중"

                away_pitcher = game.get('awayPitcherName') or game.get('awayStarterName') or '-'
                home_pitcher = game.get('homePitcherName') or game.get('homeStarterName') or '-'
                
                scraped_data[kor_away] = {
                    'status': st,
                    'awayScore': away_score,
                    'homeScore': home_score,
                    'awayPitcher': away_pitcher,
                    'homePitcher': home_pitcher,
                    'awayLineup': game.get('awayLineup', []),
                    'homeLineup': game.get('homeLineup', [])
                }
    except Exception as e:
        print("❌ 다음 스포츠 데이터 파싱 중 에러 발생:", e)

    # 🔥 파이어베이스 업데이트 (성원님 명령 완벽 적용!) 🔥
    for app_away_team, match_info in our_matches.items():
        match_id = match_info['id']
        app_home_team = match_info['home']

        matched_key = None
        for scraped_team in scraped_data.keys():
            if app_away_team in scraped_team or scraped_team in app_away_team:
                matched_key = scraped_team
                break

        if matched_key:
            data = scraped_data[matched_key]
            update_dict = {}
            
            update_dict['gameStatus'] = data['status']

            # 🚨 성원님 지시사항: 경기전이면 기존 앱에 있는 0:0 덮어쓰기 금지! 경기중/종료거나 점수가 1점이라도 났을 때만 점수 업데이트!
            if data['status'] != '경기전' or data['awayScore'] > 0 or data['homeScore'] > 0:
                update_dict['awayScore'] = data['awayScore']
                update_dict['homeScore'] = data['homeScore']
            
            # 🚨 투수와 라인업 정보가 있으면 무조건 파이어베이스에 쑤셔넣습니다!
            if data['awayPitcher'] and data['awayPitcher'] != '-': update_dict['awayPitcher'] = data['awayPitcher']
            if data['homePitcher'] and data['homePitcher'] != '-': update_dict['homePitcher'] = data['homePitcher']
            if data['awayLineup']: update_dict['awayLineup'] = data['awayLineup']
            if data['homeLineup']: update_dict['homeLineup'] = data['homeLineup']

            if update_dict:
                db.collection('lineups').document(str(match_id)).set(update_dict, merge=True)
                
                score_log = f"점수 {data['awayScore']}:{data['homeScore']}" if 'awayScore' in update_dict else "점수는 건드리지 않음"
                pitcher_log = f"투수: {data['awayPitcher']} vs {data['homePitcher']}" if data['awayPitcher'] != '-' else "투수 미정"
                print(f"    ✔️ 다음(Daum) 연동 완료! [{app_away_team} vs {app_home_team}] 상태: {data['status']} | {score_log} | {pitcher_log}")
        else:
            print(f"    ⏳ 다음 서버에 아직 [{app_away_team}] 경기 데이터가 없습니다. 대기중...")

if __name__ == "__main__":
    print("🚀 로사의 무적 KBO 봇 가동 (Daum JSON 해킹 버전)!")
    for _ in range(5):
        fetch_and_update_kbo_scores()
        time.sleep(60)
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
