from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import firebase_admin
import requests
from bs4 import BeautifulSoup
from firebase_admin import credentials

BASE_URL = "https://mykbostats.com"
DEFAULT_SCHEDULE_URL = os.getenv("KBO_SCHEDULE_URL", f"{BASE_URL}/schedule")
REQUEST_SLEEP_SECONDS = float(os.getenv("REQUEST_SLEEP_SECONDS", "0.4"))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

KST = "Asia/Seoul"
DATE_RE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4}$"
)
BATTER_LINE_RE = re.compile(r"^(?P<order>\d+)\s+(?P<name>.+?)(?:\s+#\d+)?$")
SPACE_RE = re.compile(r"\s+")
JERSEY_RE = re.compile(r"\s+#\d+$")
SKIP_TEXT = {
    "MyKBO Stats",
    "MyKBO",
    "Games",
    "Schedule",
    "Share...",
    "VS",
}


@dataclass
class ScheduleGame:
    date_label: str | None
    date_iso: str | None
    summary: str
    url: str


def now_kst() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(KST))


def normalize_space(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


def strip_jersey(text: str) -> str:
    return JERSEY_RE.sub("", normalize_space(text))


def fetch_html(url: str, *, sleep: float = REQUEST_SLEEP_SECONDS) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    if sleep:
        time.sleep(sleep)
    return response.text


def get_soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(fetch_html(url), "html.parser")


def extract_clean_lines(soup: BeautifulSoup) -> list[str]:
    text = soup.get_text("\n", strip=True)
    lines = [normalize_space(line) for line in text.splitlines()]
    return [line for line in lines if line]


def parse_date_label(label: str | None) -> str | None:
    if not label:
        return None
    try:
        return datetime.strptime(label, "%A %B %d, %Y").date().isoformat()
    except ValueError:
        return None


def title_from_soup(soup: BeautifulSoup) -> str:
    return normalize_space(soup.title.get_text(" ", strip=True)) if soup.title else ""


def build_link_map(soup: BeautifulSoup) -> dict[str, str]:
    link_map: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        text = normalize_space(a.get_text(" ", strip=True))
        href = a["href"].strip()
        if not text or not href:
            continue
        link_map[text] = urljoin(BASE_URL, href)
    return link_map


def parse_schedule_page(url: str = DEFAULT_SCHEDULE_URL) -> dict[str, Any]:
    soup = get_soup(url)
    lines = extract_clean_lines(soup)
    link_map = build_link_map(soup)

    previous_week_url = link_map.get("Previous Week")
    next_week_url = link_map.get("Next Week")

    games: list[ScheduleGame] = []
    current_date_label: str | None = None
    seen_urls: set[str] = set()

    for line in lines:
        if DATE_RE.match(line):
            current_date_label = line
            continue

        href = link_map.get(line)
        if href and "/games/" in href and href not in seen_urls:
            seen_urls.add(href)
            games.append(
                ScheduleGame(
                    date_label=current_date_label,
                    date_iso=parse_date_label(current_date_label),
                    summary=line,
                    url=href,
                )
            )

    return {
        "source_url": url,
        "previous_week_url": previous_week_url,
        "next_week_url": next_week_url,
        "games": [game.__dict__ for game in games],
    }


def find_schedule_page_for_date(target_date: str, max_hops: int = 20) -> dict[str, Any]:
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    current_url = DEFAULT_SCHEDULE_URL

    for _ in range(max_hops):
        schedule = parse_schedule_page(current_url)
        dated_games = [g for g in schedule["games"] if g["date_iso"]]
        if any(g["date_iso"] == target.isoformat() for g in dated_games):
            return schedule

        if not dated_games:
            break

        date_values = [datetime.strptime(g["date_iso"], "%Y-%m-%d").date() for g in dated_games]
        min_date = min(date_values)
        max_date = max(date_values)

        if target < min_date and schedule["previous_week_url"]:
            current_url = schedule["previous_week_url"]
            continue
        if target > max_date and schedule["next_week_url"]:
            current_url = schedule["next_week_url"]
            continue
        break

    raise ValueError(f"Could not find a schedule page containing {target_date}")


def parse_matchup(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        text = normalize_space(line)
        if " vs. " in text:
            away, home = text.split(" vs. ", 1)
            return away.strip(" #"), home.strip(" #")
        if " : " in text and not text.startswith("March "):
            m = re.match(r"^(.*?)(?:\s+\d+\s+:\s+\d+\s+)(.*?)$", text)
            if m:
                return m.group(1).strip(), m.group(2).strip()
    return None, None


def parse_linescore(lines: list[str]) -> dict[str, Any] | None:
    for i, line in enumerate(lines):
        if line != "1":
            continue

        headers: list[str] = []
        j = i
        while j < len(lines):
            headers.append(lines[j])
            if lines[j] == "B":
                break
            j += 1

        if not headers or headers[-1] != "B":
            continue

        if j + 1 >= len(lines):
            continue

        away_team = lines[j + 1]
        num_cols = len(headers)
        away_vals = lines[j + 2 : j + 2 + num_cols]
        home_idx = j + 2 + num_cols

        if len(away_vals) != num_cols or home_idx >= len(lines):
            continue

        home_team = lines[home_idx]
        home_vals = lines[home_idx + 1 : home_idx + 1 + num_cols]

        if len(home_vals) != num_cols:
            continue

        return {
            "headers": headers,
            "rows": {
                away_team: away_vals,
                home_team: home_vals,
            },
        }
    return None


def parse_starting_pitchers(lines: list[str], away_team: str | None, home_team: str | None) -> dict[str, str] | None:
    if "Pitching" in lines and away_team and home_team:
        result: dict[str, str] = {}
        idx = lines.index("Pitching") + 1

        for team_name in (away_team, home_team):
            while idx < len(lines) and lines[idx] != team_name:
                if lines[idx] == "Plays":
                    return result or None
                idx += 1

            if idx >= len(lines):
                break

            idx += 1
            if idx < len(lines) and lines[idx].startswith("ERA "):
                idx += 1

            while idx < len(lines):
                line = lines[idx]
                if line in {away_team, home_team, "Plays"}:
                    break
                if re.fullmatch(r"[0-9.⅓⅔ ]+", line):
                    idx += 1
                    continue
                if line not in SKIP_TEXT:
                    result[team_name] = strip_jersey(line)
                    break
                idx += 1

        if result:
            return result

    return None


def parse_starting_batters(lines: list[str], away_team: str | None, home_team: str | None) -> dict[str, list[dict[str, Any]]] | None:
    if "Batting" not in lines or not away_team or not home_team:
        return None

    idx = lines.index("Batting") + 1
    team_order = [away_team, home_team]
    result: dict[str, list[dict[str, Any]]] = {}

    for team_name in team_order:
        while idx < len(lines) and lines[idx] != team_name:
            if lines[idx] == "Pitching":
                return result or None
            idx += 1

        if idx >= len(lines):
            break

        idx += 1
        if idx < len(lines) and "Pos" in lines[idx]:
            idx += 1

        starters: list[dict[str, Any]] = []
        while idx < len(lines):
            line = lines[idx]
            if line in team_order or line == "Pitching":
                break

            if line.startswith("↳"):
                idx += 2
                continue

            match = BATTER_LINE_RE.match(line)
            if match:
                order = int(match.group("order"))
                name = strip_jersey(match.group("name"))
                pos = None
                if idx + 1 < len(lines):
                    pos = lines[idx + 1].split()[0]
                starters.append({
                    "order": order,
                    "name": name,
                    "pos": pos,
                })
                idx += 2
                continue

            idx += 1

        if starters:
            result[team_name] = starters[:9]

    return result or None


def extract_game_id(url: str) -> str:
    m = re.search(r"/games/(\d+)-", url)
    if m:
        return m.group(1)
    return re.sub(r"[^a-zA-Z0-9_-]", "_", url.rsplit("/", 1)[-1])


def parse_game_page(url: str) -> dict[str, Any]:
    soup = get_soup(url)
    lines = extract_clean_lines(soup)

    away_team, home_team = parse_matchup(lines)
    linescore = parse_linescore(lines)

    if linescore and len(linescore["rows"]) == 2:
        team_names = list(linescore["rows"].keys())
        away_team = away_team or team_names[0]
        home_team = home_team or team_names[1]

    venue = None
    broadcast = None
    for line in lines:
        if line.startswith("Venue "):
            venue = line.removeprefix("Venue ").strip()
        elif line.startswith("Broadcast "):
            broadcast = line.removeprefix("Broadcast ").strip()

    starting_pitchers = parse_starting_pitchers(lines, away_team, home_team)
    starting_batters = parse_starting_batters(lines, away_team, home_team)

    return {
        "gameId": extract_game_id(url),
        "sourceUrl": url,
        "pageTitle": title_from_soup(soup),
        "awayTeam": away_team,
        "homeTeam": home_team,
        "venue": venue,
        "broadcast": broadcast,
        "linescore": linescore,
        "startingPitchers": starting_pitchers,
        "startingBatters": starting_batters,
        "lineupPublished": bool(
            starting_batters
            and away_team in starting_batters
            and home_team in starting_batters
            and len(starting_batters[away_team]) >= 9
            and len(starting_batters[home_team]) >= 9
        ),
        "fetchedAt": now_kst().isoformat(),
    }


def get_today_games(target_date: str | None = None) -> dict[str, Any]:
    if target_date is None:
        target_date = now_kst().date().isoformat()

    schedule = find_schedule_page_for_date(target_date)
    games = [g for g in schedule["games"] if g["date_iso"] == target_date]

    parsed_games = []
    for game in games:
        payload = parse_game_page(game["url"])
        payload["date"] = target_date
        payload["scheduleSummary"] = game["summary"]
        parsed_games.append(payload)

    return {
        "date": target_date,
        "gameCount": len(parsed_games),
        "games": parsed_games,
        "syncedAt": now_kst().isoformat(),
    }


def load_service_account() -> credentials.Base:
    raw_json = os.getenv("FIREBASE_KEY") or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")

    if raw_json:
        return credentials.Certificate(json.loads(raw_json))
    if path:
        return credentials.Certificate(path)
    return credentials.ApplicationDefault()


def init_firebase() -> str:
    backend = (os.getenv("FIREBASE_BACKEND") or "firestore").strip().lower()

    if firebase_admin._apps:
        return backend

    cred = load_service_account()
    options: dict[str, Any] = {}

    if backend == "rtdb":
        database_url = os.getenv("FIREBASE_DATABASE_URL")
        if not database_url:
            raise ValueError("FIREBASE_DATABASE_URL is required when FIREBASE_BACKEND=rtdb")
        options["databaseURL"] = database_url

    firebase_admin.initialize_app(cred, options)
    return backend


def upload_to_firestore(data: dict[str, Any]) -> list[str]:
    from firebase_admin import firestore

    collection_name = (os.getenv("FIREBASE_COLLECTION") or "kboGames").strip()
    meta_collection = (os.getenv("FIREBASE_META_COLLECTION") or "kboSyncMeta").strip()

    db = firestore.client()
    written_ids: list[str] = []

    for game in data["games"]:
        doc_id = game["gameId"]
        db.collection(collection_name).document(doc_id).set(game, merge=True)
        written_ids.append(doc_id)

    db.collection(meta_collection).document(data["date"]).set({
        "date": data["date"],
        "gameCount": data["gameCount"],
        "gameIds": written_ids,
        "syncedAt": data["syncedAt"],
    }, merge=True)

    return written_ids


def upload_to_rtdb(data: dict[str, Any]) -> list[str]:
    from firebase_admin import db

    base_path = (os.getenv("FIREBASE_DB_PATH") or "kbo/games").strip("/")
    meta_path = (os.getenv("FIREBASE_META_PATH") or "kbo/meta").strip("/")

    written_ids: list[str] = []
    for game in data["games"]:
        game_id = game["gameId"]
        db.reference(f"{base_path}/{data['date']}/{game_id}").set(game)
        written_ids.append(game_id)

    db.reference(f"{meta_path}/{data['date']}").set({
        "date": data["date"],
        "gameCount": data["gameCount"],
        "gameIds": written_ids,
        "syncedAt": data["syncedAt"],
    })

    return written_ids


def sync_today_to_firebase(target_date: str | None = None) -> dict[str, Any]:
    data = get_today_games(target_date)
    backend = init_firebase()

    if backend == "firestore":
        written_ids = upload_to_firestore(data)
    elif backend == "rtdb":
        written_ids = upload_to_rtdb(data)
    else:
        raise ValueError("FIREBASE_BACKEND must be either 'firestore' or 'rtdb'")

    lineup_ready = sum(1 for g in data["games"] if g["lineupPublished"])
    return {
        "backend": backend,
        "date": data["date"],
        "gameCount": data["gameCount"],
        "lineupReadyCount": lineup_ready,
        "writtenGameIds": written_ids,
        "syncedAt": data["syncedAt"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync MyKBO Stats game data to Firebase.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    today_parser = subparsers.add_parser("sync-today", help="Scrape today's games and upload them to Firebase.")
    today_parser.add_argument("--date", help="Target date in YYYY-MM-DD. Defaults to today in Asia/Seoul.")

    dump_parser = subparsers.add_parser("dump-today", help="Print today's games as JSON only.")
    dump_parser.add_argument("--date", help="Target date in YYYY-MM-DD. Defaults to today in Asia/Seoul.")

    game_parser = subparsers.add_parser("dump-game", help="Print one game page as JSON.")
    game_parser.add_argument("url", help="MyKBO game URL")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "sync-today":
        result = sync_today_to_firebase(args.date)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "dump-today":
        print(json.dumps(get_today_games(args.date), ensure_ascii=False, indent=2))
        return

    if args.command == "dump-game":
        print(json.dumps(parse_game_page(args.url), ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
