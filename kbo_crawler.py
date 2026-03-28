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
    date_code = kst_time.strftime('%Y%m%d') # 예: 20260329 (로사님이 찾아주신 링크 형식!)
    
    print(f"\n[{kst_time.strftime('%H:%M:%S')}] MyKBO.com 상세 페이지 딥서치 시작 ({today_str})")

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

    headers = {"User-Agent": "Mozilla/5.0"}
    team_map = {'KIA':'KIA', 'SSG':'SSG', 'KT':'KT', 'LG':'LG', 'LOTTE':'롯데', 'SAMSUNG':'삼성', 'DOOSAN':'두산', 'NC':'NC', 'KIWOOM':'키움', 'HANWHA':'한화'}
    
    # 🔥 1. 메인 페이지만 보지 않고, 스케줄 페이지 전체를 뒤져서 '오늘 날짜(date_code)'가 박힌 상세 링크를 모두 수집합니다! 🔥
    urls_to_check = [
        "https://mykbostats.com/",
        "https://mykbostats.com/schedule",
        "https://mykbostats.com/games"
    ]
    
    game_links = set()
    for base_url in urls_to_check:
        try:
            res = requests.get(base_url, headers=headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                # 로사님이 찾아주신 정확한 링크 패턴을 추적! (/games/...-20260329)
                if '/games/' in a['href'] and date_code in a['href']:
                    game_links.add(a['href'])
        except Exception:
            continue

    if not game_links:
        print(f"⚠️ 사이트 전체를 뒤졌지만 오늘({date_code}) 경기 링크를 아직 찾을 수 없습니다.")
        return

    print(f"🔗 MyKBO에서 오늘 경기 상세 링크 {len(game_links)}개 발견! 즉시 접속하여 라인업을 가져옵니다...")

    scraped_data = {}

    # 🔥 2. 찾은 상세 페이지로 다이렉트로 들어가서 투수, 라인업, 점수를 긁어옵니다! 🔥
    for href in game_links:
        try:
            # URL에서 팀 이름 추출 (예: /games/13252-Kia-vs-SSG-20260329)
            parts = href.split('-')
            vs_idx = parts.index('vs')
            eng_away = parts[vs_idx - 1].upper()
            eng_home = parts[vs_idx + 1].upper()
            
            kor_away = team_map.get(eng_away, eng_away)
            kor_home = team_map.get(eng_home, eng_home)

            # 로사님이 찾은 그 상세 페이지로 직접 접속!
            g_url = "https://mykbostats.com" + href if href.startswith('/') else href
            g_res = requests.get(g_url, headers=headers)
            g_soup = BeautifulSoup(g_res.text, 'html.parser')
            g_text = g_soup.get_text(separator='\n')

            # 상태 추출
            st = "경기전"
            if 'FINAL' in g_text.upper() or 'F/' in g_text.upper(): st = "종료"
            elif 'CANCEL' in g_text.upper() or 'POSTPONED' in g_text.upper(): st = "취소"
            elif 'BOT ' in g_text.upper() or 'TOP ' in g_text.upper() or 'MID ' in g_text.upper(): st = "경기중"

            # ⚾ 선발 투수 완벽 추출
            away_pitcher, home_pitcher = '-', '-'
            pitcher_matches = re.findall(r'Probable Pitchers.*?([A-Za-z\-\s]+).*?vs.*?([A-Za-z\-\s]+)', g_text, re.IGNORECASE | re.DOTALL)
            if pitcher_matches:
                away_pitcher = pitcher_matches[0][0].strip()
                home_pitcher = pitcher_matches[0][1].strip()
            else:
                wp = re.search(r'W:\s*([A-Za-z\-\s]+)', g_text)
                lp = re.search(r'L:\s*([A-Za-z\-\s]+)', g_text)
                if wp: away_pitcher = wp.group(1).strip()
                if lp: home_pitcher = lp.group(1).strip()

            # ⚾ 선발 타자 라인업 완벽 추출
            away_lineup, home_lineup = [], []
            batters = re.findall(r'-\s+([A-Za-z\-\s]+)\s+#\d+\.', g_text)
            if len(batters) >= 18:
                away_lineup = [b.strip() for b in batters[:9]]
                home_lineup = [b.strip() for b in batters[9:18]]

            # 점수 추출 (점수가 텍스트 어딘가에 찍혀있다면 가져옵니다)
            away_score, home_score = 0, 0
            score_match = re.search(rf'{eng_away}\s+(\d+)\s*[@,\-]?\s*{eng_home}\s+(\d+)', g_text, re.IGNORECASE)
            if not score_match:
                score_match = re.search(rf'{eng_away}\s+(\d+)\s*[@,\-]?\s*(\d+)\s*{eng_home}', g_text, re.IGNORECASE)
            
            if score_match:
                away_score = int(score_match.group(1))
                home_score = int(score_match.group(2))
                if st == "경기전" and (away_score > 0 or home_score > 0):
                    st = "경기중" # 점수가 발견되면 최소 경기중으로 판단

            scraped_data[kor_away] = {
                'home': kor_home,
                'status': st,
                'awayScore': away_score,
                'homeScore': home_score,
                'awayPitcher': away_pitcher,
                'homePitcher': home_pitcher,
                'awayLineup': away_lineup,
                'homeLineup': home_lineup
            }
        except Exception as e:
            print(f"상세 페이지({href}) 분석 에러: {e}")
            continue

    # 🔥 3. 파이어베이스 업데이트 (로사님 명령: 점수 없으면 0:0 덮어쓰기 금지! 라인업만 쏙!) 🔥
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

            # 🚨 로사님 핵심 명령: 점수가 0:0 이고 아직 경기전이면 '점수 데이터' 자체를 덮어쓰지 않고 무시합니다!
            if data['status'] != '경기전' or data['awayScore'] > 0 or data['homeScore'] > 0:
                update_dict['awayScore'] = data['awayScore']
                update_dict['homeScore'] = data['homeScore']
            
            # 투수 및 라인업이 찾아졌다면 점수랑 상관없이 무조건 쑤셔넣습니다!
            if data['awayPitcher'] != '-': update_dict['awayPitcher'] = data['awayPitcher']
            if data['homePitcher'] != '-': update_dict['homePitcher'] = data['homePitcher']
            if data['awayLineup']: update_dict['awayLineup'] = data['awayLineup']
            if data['homeLineup']: update_dict['homeLineup'] = data['homeLineup']

            if update_dict:
                db.collection('lineups').document(str(match_id)).set(update_dict, merge=True)
                
                score_log = f"점수 {data['awayScore']}:{data['homeScore']}" if 'awayScore' in update_dict else "점수는 건드리지 않음"
                lineup_log = "투수/라인업 추출 성공!" if data['awayLineup'] else "라인업 아직 없음"
                print(f"    ✔️ 완벽 연동 완료! [{app_away_team} vs {app_home_team}] 상태: {data['status']} | {score_log} | {lineup_log}")
        else:
            print(f"    ⏳ 발견된 링크 중에 {app_away_team} 경기가 없습니다. 대기중...")

if __name__ == "__main__":
    print("🚀 로사의 KBO 봇 가동 (MyKBO 상세페이지 딥서치 & 라인업 완벽버전)!")
    for _ in range(5):
        fetch_and_update_kbo_scores()
        time.sleep(60)
    print("🏁 5분 사이클 완료. 깃허브가 곧 다시 실행시켜 줍니다!")
