import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import time
import requests
from bs4 import BeautifulSoup

# ==========================================
# 🔥 1. 파이어베이스 접속 🔥
# ==========================================
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    cred_dict = json.loads(firebase_secret)
    cred = credentials.Certificate(cred_dict)
    print("✅ 깃허브 Secrets에서 키 로드 완료!")
else:
    cred = credentials.Certificate("my-firebase-key.json")
    print("✅ 로컬 파일에서 키 로드 완료!")

# 이미 초기화된 경우 방지
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🔍 JSON 구조에서 특정 경기 데이터 무조건 찾기 (재귀 탐색)
# ==========================================
def find_game_data(data, match_id):
    """복잡한 네이버 JSON 구조 안에서 match_id를 가진 딕셔너리를 무조건 찾아냅니다."""
    if isinstance(data, dict):
        # gameId가 일치하고 상태값(gameStatusName)이 있는 진짜 경기 데이터를 찾음
        if data.get('gameId') == match_id and 'gameStatusName' in data:
            return data
        for key, value in data.items():
            result = find_game_data(value, match_id)
            if result: return result
    elif isinstance(data, list):
        for item in data:
            result = find_game_data(item, match_id)
            if result: return result
    return None

# ==========================================
# 🕷️ 2. 네이버 스포츠 크롤링 (순수 데이터 모드) 🕷️
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 경기 데이터 수집 중...")
    url = f"https://m.sports.naver.com/game/{naver_match_id}/record"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            print("❌ 데이터를 찾지 못했습니다. (__NEXT_DATA__ 태그 없음)")
            return None
            
        data = json.loads(script_tag.string)
        
        # 🔥 기존 고정된 경로 대신, 스스로 데이터를 찾아오도록 스마트 탐색 적용
        target_game = find_game_data(data, naver_match_id)
        
        if not target_game:
            print(f"❌ 경기를 찾을 수 없습니다. (데이터 구조 내에 해당 ID 없음)")
            return None

        # 진짜 점수 및 상태 추출 (네이버 내부 필드명이 awayScore 또는 awayTeamScore로 바뀔 때를 모두 대비)
        game_status = target_game.get('gameStatusName', '경기전')
        away_score = target_game.get('awayScore', target_game.get('awayTeamScore', 0))
        home_score = target_game.get('homeScore', target_game.get('homeTeamScore', 0))
        
        # 선발 투수 정보가 있다면 덤으로 가져오기
        away_pitcher = target_game.get('awayStarterName', '미정')
        home_pitcher = target_game.get('homeStarterName', '미정')
        
        print(f"✅ 수집 완료: [{game_status}] {away_score}:{home_score}")
        
        return {
            "gameStatus": game_status,
            "awayScore": int(away_score) if away_score else 0,
            "homeScore": int(home_score) if home_score else 0,
            "awayPitcher": away_pitcher,
            "homePitcher": home_pitcher,
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }
    except Exception as e:
        print(f"❌ 크롤링 에러 발생: {e}")
        return None

def update_live_data_to_firebase(app_match_id, naver_match_id):
    live_data = fetch_naver_live_data(naver_match_id)
    if live_data:
        doc_ref = db.collection('lineups').document(str(app_match_id))
        # 🔥 merge=True : 기존에 저장된 라인업 정보 등이 있다면 날아가지 않고 '점수와 상태'만 덮어쓰기 합니다!
        doc_ref.set(live_data, merge=True)
        print(f"🚀 파이어베이스 업데이트 완료! (앱 매치 ID: {app_match_id})")
    else:
        print("⚠️ 수집된 데이터가 없어 파이어베이스 업데이트를 수행하지 않았습니다.")

if __name__ == "__main__":
    # 3월 24일 KIA vs 삼성 (시범경기 테스트)
    update_live_data_to_firebase(app_match_id=99, naver_match_id="20260324HTSS02026")import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import time
import requests
from bs4 import BeautifulSoup

# ==========================================
# 🔥 1. 파이어베이스 접속 🔥
# ==========================================
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_secret:
    cred_dict = json.loads(firebase_secret)
    cred = credentials.Certificate(cred_dict)
    print("✅ 깃허브 Secrets에서 키 로드 완료!")
else:
    cred = credentials.Certificate("my-firebase-key.json")
    print("✅ 로컬 파일에서 키 로드 완료!")

# 이미 초기화된 경우 방지
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================
# 🔍 JSON 구조에서 특정 경기 데이터 무조건 찾기 (재귀 탐색)
# ==========================================
def find_game_data(data, match_id):
    """복잡한 네이버 JSON 구조 안에서 match_id를 가진 딕셔너리를 무조건 찾아냅니다."""
    if isinstance(data, dict):
        # gameId가 일치하고 상태값(gameStatusName)이 있는 진짜 경기 데이터를 찾음
        if data.get('gameId') == match_id and 'gameStatusName' in data:
            return data
        for key, value in data.items():
            result = find_game_data(value, match_id)
            if result: return result
    elif isinstance(data, list):
        for item in data:
            result = find_game_data(item, match_id)
            if result: return result
    return None

# ==========================================
# 🕷️ 2. 네이버 스포츠 크롤링 (순수 데이터 모드) 🕷️
# ==========================================
def fetch_naver_live_data(naver_match_id):
    print(f"[{naver_match_id}] 경기 데이터 수집 중...")
    url = f"https://m.sports.naver.com/game/{naver_match_id}/record"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            print("❌ 데이터를 찾지 못했습니다. (__NEXT_DATA__ 태그 없음)")
            return None
            
        data = json.loads(script_tag.string)
        
        # 🔥 기존 고정된 경로 대신, 스스로 데이터를 찾아오도록 스마트 탐색 적용
        target_game = find_game_data(data, naver_match_id)
        
        if not target_game:
            print(f"❌ 경기를 찾을 수 없습니다. (데이터 구조 내에 해당 ID 없음)")
            return None

        # 진짜 점수 및 상태 추출 (네이버 내부 필드명이 awayScore 또는 awayTeamScore로 바뀔 때를 모두 대비)
        game_status = target_game.get('gameStatusName', '경기전')
        away_score = target_game.get('awayScore', target_game.get('awayTeamScore', 0))
        home_score = target_game.get('homeScore', target_game.get('homeTeamScore', 0))
        
        # 선발 투수 정보가 있다면 덤으로 가져오기
        away_pitcher = target_game.get('awayStarterName', '미정')
        home_pitcher = target_game.get('homeStarterName', '미정')
        
        print(f"✅ 수집 완료: [{game_status}] {away_score}:{home_score}")
        
        return {
            "gameStatus": game_status,
            "awayScore": int(away_score) if away_score else 0,
            "homeScore": int(home_score) if home_score else 0,
            "awayPitcher": away_pitcher,
            "homePitcher": home_pitcher,
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }
    except Exception as e:
        print(f"❌ 크롤링 에러 발생: {e}")
        return None

def update_live_data_to_firebase(app_match_id, naver_match_id):
    live_data = fetch_naver_live_data(naver_match_id)
    if live_data:
        doc_ref = db.collection('lineups').document(str(app_match_id))
        # 🔥 merge=True : 기존에 저장된 라인업 정보 등이 있다면 날아가지 않고 '점수와 상태'만 덮어쓰기 합니다!
        doc_ref.set(live_data, merge=True)
        print(f"🚀 파이어베이스 업데이트 완료! (앱 매치 ID: {app_match_id})")
    else:
        print("⚠️ 수집된 데이터가 없어 파이어베이스 업데이트를 수행하지 않았습니다.")

if __name__ == "__main__":
    # 3월 24일 KIA vs 삼성 (시범경기 테스트)
    update_live_data_to_firebase(app_match_id=99, naver_match_id="20260324HTSS02026")
