import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import time
from bs4 import BeautifulSoup
import re

# 파이어베이스 관리자 권한 연결
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

def fetch_and_update_kbo_scores():
    # 무조건 한국 시간(KST)으로 맞춤
    kst_time = datetime.utcnow() + timedelta(hours=9)
    today_str = kst_time.strftime('%Y-%m-%d')
    print(f"\n[{kst_time.strftime('%H:%M:%S')}] MyKBO.com 단독 데이터 수집 시작 ({today_str})")

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

    # 🔥 어웨이만 한다는 오해를 풀기 위해, 양 팀 모두 확실하게 로그에 출력합니다! 🔥
    print(f"🔎 우리 앱에 등록된 오늘 경기: {', '.join(display_list)}")

    url_mykbo = "https://mykbostats.com/"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        res_mykbo = requests.get(url_mykbo, headers=headers)
        soup = BeautifulSoup(res_mykbo.text, 'html.parser')
    except Exception as e:
        print(f"❌ 사이트 접속 오류: {e}")
        return

    team_map = {'KIA':'KIA', 'SSG':'SSG', 'KT':'KT', 'LG':'LG', 'LOTTE':'롯데', 'SAMSUNG':'삼성', 'DOOSAN':'두산', 'NC':'NC', 'KIWOOM':'키움', 'HANWHA':'한화'}
    scraped_data = {}

    # 🔥 1. 메인 페이지에서 점수 및 상태 긁어오기
    lines = soup.get_text(separator='\n').split('\n')
    for line in lines:
        txt = line.strip().upper()
        found_teams = [kor for eng, kor in team_map.items() if eng in txt]
        
        if len(found_teams) >= 2:
            away = found_teams[0]
            home = found_teams[1]
            st = "경기전"
            if 'FINAL' in txt or 'F/' in txt: st = "종료"
            elif 'CANCEL' in txt or 'POSTPONED' in txt or 'RAIN' in txt: st = "취소"
            elif 'BOT ' in txt or 'TOP ' in txt or 'MID ' in txt: st = "경기중"
            
            nums = [int(s) for s in txt.split() if s.isdigit()]
            away_score = nums[0] if len(nums) > 0 else 0
            home_score = nums[1] if len(nums) > 1 else 0
            
            if len(nums) >= 2 and st == "경기전": st = "경기중"
            
            scraped_data[away] = {
                'home': home,
                'status': st,
                'awayScore': away_score,
                'homeScore': home_score,
                'awayPitcher': '-',
                'homePitcher': '-',
                'awayLineup': [],
                'homeLineup': []
            }

    # 🔥 2. 상세 페이지로 깊게 들어가서 '선발투수'와 '선발타자' 라인업을 기필코 찾아냅니다!
    game_links = soup.find_all('a', href=re.compile(r'/games/\d+'))
    for link in game_links:
        g_url = "https://mykbostats.com" + link['href']
        try:
            g_res = requests.get(g_url, headers=headers)
            g_soup = BeautifulSoup(g_res.text, 'html.parser')
            g_text = g_soup.get_text(separator='\n')
            
            found_teams_in_page = [kor for eng, kor in team_map.items() if eng in g_text.upper()]
            if len(found_teams_in_page) < 2:
                continue
                
            away = found_teams_in_page[0]
            home = found_teams_in_page[1]

            if away not in scraped_data:
                scraped_data[away] = {'home': home, 'status': '경기전', 'awayScore': 0, 'homeScore': 0, 'awayPitcher': '-', 'homePitcher': '-', 'awayLineup': [], 'homeLineup': []}

            # ⚾ 선발 투수 추출 (Probable Pitchers 또는 경기 후 승/패 투수 항목 찾기)
            pitcher_matches = re.findall(r'Probable Pitchers.*?([A-Za-z\-\s]+).*?vs.*?([A-Za-z\-\s]+)', g_text, re.IGNORECASE | re.DOTALL)
            if pitcher_matches:
                scraped_data[away]['awayPitcher'] = pitcher_matches[0][0].strip()
                scraped_data[away]['homePitcher'] = pitcher_matches[0][1].strip()
            else:
                wp = re.search(r'W:\s*([A-Za-z\-\s]+)', g_text)
                lp = re.search(r'L:\s*([A-Za-z\-\s]+)', g_text)
                if wp: scraped_data[away]['awayPitcher'] = wp.group(1).strip()
                if lp: scraped_data[away]['homePitcher'] = lp.group(1).strip()

            # ⚾ 선발 타자 라인업 추출 (Batting 테이블의 선수명 9명씩 찾기)
            batters = re.findall(r'-\s+([A-Za-z\-\s]+)\s+#\d+\.', g_text)
            if len(batters) >= 18:
                scraped_data[away]['awayLineup'] = [b.strip() for b in batters[:9]]
                scraped_data[away]['homeLineup'] = [b.strip() for b in batters[9:18]]

        except Exception:
            pass

    # 🔥 3. 점수판이 없으면 0:0으로 덮어쓰지 않고, 찾은 투수/타자만 쏙 넣습니다!
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
            
            # 🚨 로사님 명령 적용: 경기가 시작했거나 점수가 찍혀있을 때만 점수 업데이트 (무작정 0:0 초기화 금지!)
            if data['status'] != '경기전' or (data['awayScore'] > 0 or data['homeScore'] > 0):
                update_dict['gameStatus'] = data['status']
                update_dict['awayScore'] = data['awayScore']
                update_dict['homeScore'] = data['homeScore']
            else:
                update_dict['gameStatus'] = '경기전'
            
            # 🚨 투수와 라인업을 긁어왔다면 점수랑 상관없이 무조건 쑤셔넣습니다!
            if data['awayPitcher'] != '-': update_dict['awayPitcher'] = data['awayPitcher']
            if data['homePitcher'] != '-': update_dict['homePitcher'] = data['homePitcher']
            if data['awayLineup']: update_dict['awayLineup'] = data['awayLineup']
            if data['homeLineup']: update_dict['homeLineup'] = data['homeLineup']

            if update_dict:
                db.collection('lineups').document(str(match_id)).set(update_dict, merge=True)
                msg_tail = f"점수: {data['awayScore']}:{data['homeScore']}" if 'awayScore' in update_dict else "선발투수/타자 갱신 완료"
                print(f"    ✔️ 데이터 업데이트! [{app_away_team} vs {app_home_team}] {msg_tail}")
        else:
            print(f"    ⏳ 사이트에 아직 매치 정보가 없습니다. 대기중... ({app_away_team} vs {app_home_team})")

if __name__ == "__main__":
    print("🚀 로사의 KBO 봇 가동 (MyKBO 단독 & 라인업 추출 버전)!")
    for _ in range(5):
        fetch_and_update_kbo_scores()
        time.sleep(60)
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
