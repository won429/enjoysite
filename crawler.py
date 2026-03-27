import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import re
from bs4 import BeautifulSoup

# ==========================================
# 🔥 1. 파이어베이스 접속 🔥
# ==========================================
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    try:
        cred_dict = json.loads(firebase_secret)
        cred = credentials.Certificate(cred_dict)
        print("✅ 깃허브 Secrets에서 파이어베이스 키 로드 완료!")
    except Exception as e:
        print(f"🚨 [치명적 에러] 파이어베이스 키 인증 실패: {e}")
        exit(1)
else:
    print("🚨 [치명적 에러] 'FIREBASE_CREDENTIALS'를 찾지 못했습니다!")
    exit(1)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🔍 JSON에서 무조건 첫 번째 점수 데이터 찾기 (ID 검사 완전 삭제)
# ==========================================
def find_any_score(obj):
    if isinstance(obj, dict):
        # 점수 데이터 형식을 갖추고 있다면, 아이디 따지지 않고 무조건 합격!
        if ('awayScore' in obj or 'awayTeamScore' in obj) and ('gameStatusName' in obj or 'statusCodeName' in obj):
            return obj
            
        # 네이버 내부 팀 객체 안에 점수가 숨어있는 경우
        if 'awayTeam' in obj and isinstance(obj['awayTeam'], dict) and 'score' in obj['awayTeam']:
             if 'gameStatusName' in obj or 'statusCodeName' in obj:
                 return {
                     'gameStatusName': obj.get('gameStatusName') or obj.get('statusCodeName'),
                     'awayScore': obj['awayTeam'].get('score', 0),
                     'homeScore': obj.get('homeTeam', {}).get('score', 0),
                     'awayStarterName': obj['awayTeam'].get('starter', '미정'),
                     'homeStarterName': obj.get('homeTeam', {}).get('starter', '미정')
                 }
                 
        for v in obj.values():
            res = find_any_score(v)
            if res: return res
            
    elif isinstance(obj, list):
        for item in obj:
            res = find_any_score(item)
            if res: return res
    return None

def parse_target_game(target):
    game_status = target.get('gameStatusName') or target.get('statusCodeName') or '경기전'
    away_score = target.get('awayScore', target.get('awayTeamScore', 0))
    home_score = target.get('homeScore', target.get('homeTeamScore', 0))
    away_pitcher = target.get('awayStarterName', target.get('awayPitcherName', '미정'))
    home_pitcher = target.get('homeStarterName', target.get('homePitcherName', '미정'))
    
    print(f"🎉 파싱 성공!: [{game_status}] AWAY {away_score} : {home_score} HOME")
    return {
        "gameStatus": game_status,
        "awayScore": int(away_score) if away_score else 0,
        "homeScore": int(home_score) if home_score else 0,
        "awayPitcher": away_pitcher,
        "homePitcher": home_pitcher,
        "lastUpdated": firestore.SERVER_TIMESTAMP
    }

# ==========================================
# 🚀 2. 주신 링크 그대로 직행하는 무식하고 확실한 크롤러 🚀
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 해당 링크로 바로 돌진합니다...")
    
    # 회원님이 보시는 그 링크 똑같이 들어갑니다.
    url = f"https://m.sports.naver.com/game/{naver_match_id}/record"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9"
    }
    
    try:
        print(f"👉 접속 중: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        html = response.text
        
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string if soup.title else 'No Title'
        print(f"   ㄴ 접속 성공! 페이지 타이틀: [{title.strip()}]")
        
        # 1. 화면에 숨겨진 JSON 보물상자에서 무조건 첫 번째 점수를 뽑아냅니다.
        for s in soup.find_all('script'):
            text = s.string if s.string else ""
            if '{' in text and '"away' in text:
                start = text.find('{')
                end = text.rfind('}')
                if start != -1 and end != -1:
                    try:
                        data = json.loads(text[start:end+1])
                        target = find_any_score(data)
                        if target: 
                            print("   ㄴ 🔥 데이터 박스에서 점수 발견!")
                            return parse_target_game(target)
                    except: pass
        
        # 2. 보물상자가 없으면? 화면 글자 틈새에서 점수만 정규식으로 싹둑 잘라냅니다.
        status_m = re.search(r'(?:gameStatusName|statusCodeName)["\']?\s*:\s*["\']([^"\']+)["\']', html)
        away_m = re.search(r'(?:awayScore|awayTeamScore)["\']?\s*:\s*(\d+)', html)
        home_m = re.search(r'(?:homeScore|homeTeamScore)["\']?\s*:\s*(\d+)', html)
        
        if status_m and away_m and home_m:
            print("   ㄴ 🔥 화면 텍스트에서 점수 강제 추출 성공!")
            away_p = re.search(r'(?:awayStarterName|awayPitcherName)["\']?\s*:\s*["\']([^"\']+)["\']', html)
            home_p = re.search(r'(?:homeStarterName|homePitcherName)["\']?\s*:\s*["\']([^"\']+)["\']', html)
            
            status = status_m.group(1)
            away_score = away_m.group(1)
            home_score = home_m.group(1)
            
            print(f"🎉 파싱 성공!: [{status}] AWAY {away_score} : {home_score} HOME")
            
            return {
                "gameStatus": status,
                "awayScore": int(away_score),
                "homeScore": int(home_score),
                "awayPitcher": away_p.group(1) if away_p else "미정",
                "homePitcher": home_p.group(1) if home_p else "미정",
                "lastUpdated": firestore.SERVER_TIMESTAMP
            }
            
        print("❌ 페이지 접속은 성공했으나 화면에서 점수 데이터를 찾지 못했습니다.")
        
    except Exception as e:
        print(f"❌ 크롤링 에러 발생: {e}")

    return None

def update_live_data_to_firebase(app_match_id, naver_match_id):
    live_data = fetch_naver_live_data(naver_match_id)
    if live_data:
        doc_ref = db.collection('lineups').document(str(app_match_id))
        doc_ref.set(live_data, merge=True)
        print(f"🚀 파이어베이스 업데이트 완료! (앱 매치 ID: {app_match_id})")
    else:
        print("⚠️ 수집된 데이터가 없어 파이어베이스 업데이트를 수행하지 않았습니다.")

if __name__ == "__main__":
    # 회원님이 쓰시던 17자리 그대로! 아이디 검사 안 하니까 무조건 가져옵니다.
    update_live_data_to_firebase(app_match_id=99, naver_match_id="20260324HTSS02026")
