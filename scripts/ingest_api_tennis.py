"""
Ingest data from the API-Tennis service into Supabase ingestion tables.

The script pulls players, tournaments, and ranking snapshots, normalizes them to
fit the ingest_* tables, and upserts using the unique constraints defined on the
schema.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

import requests


API_BASE_URL = os.getenv("API_TENNIS_BASE_URL", "https://api.api-tennis.com/tennis")
API_KEY = os.getenv("API_TENNIS_KEY")
API_KEY_HEADER = os.getenv("API_TENNIS_KEY_HEADER", "x-api-key")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
SOURCE_SLUG = "api-tennis"
SOURCE_NAME = "API-Tennis"


class IngestionError(RuntimeError):
    """Raised when a required step fails."""


def require_env(value: Optional[str], name: str) -> str:
    if not value:
        raise IngestionError(f"Missing required environment variable: {name}")
    return value


def fetch_api(endpoint: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Call an API-Tennis endpoint and return the JSON payload."""
    api_key = require_env(API_KEY, "API_TENNIS_KEY")
    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    response = requests.get(url, headers={API_KEY_HEADER: api_key}, params=params, timeout=30)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise IngestionError(f"Invalid JSON payload from {url}") from exc


def supabase_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
) -> Any:
    supabase_url = require_env(SUPABASE_URL, "SUPABASE_URL")
    supabase_key = require_env(SUPABASE_SERVICE_ROLE_KEY, "SUPABASE_SERVICE_ROLE_KEY")
    url = f"{supabase_url.rstrip('/')}/rest/v1/{path}"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=30)
    if not response.ok:
        raise IngestionError(f"Supabase request failed ({response.status_code}): {response.text}")
    if response.text:
        return response.json()
    return None


def fetch_lookup_table(table: str, key: str) -> Dict[str, Any]:
    rows = supabase_request("GET", table, params={"select": "*"})
    return {row[key]: row for row in rows}


def upsert_rows(table: str, rows: List[Dict[str, Any]], on_conflict: str) -> List[Dict[str, Any]]:
    if not rows:
        return []
    return supabase_request(
        "POST",
        table,
        params={"on_conflict": on_conflict, "return": "representation"},
        json_body=rows,
    )


def normalize_country_code(country: Optional[str]) -> Optional[str]:
    if not country:
        return None
    code = country.strip().upper()
    return code[:3] if len(code) > 3 else code


def normalize_date(value: Optional[Any]) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return dt.date.fromtimestamp(value).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(str(value), fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return None


def normalize_tour_slug(record: Dict[str, Any]) -> Optional[str]:
    sex = (record.get("sex") or record.get("gender") or "").lower()
    tour = (record.get("tour") or record.get("circuit") or "").lower()
    if sex.startswith("w") or tour == "wta":
        return "wta"
    if sex.startswith("m") or tour == "atp":
        return "atp"
    return None


def normalize_surface_slug(surface: Optional[str]) -> Optional[str]:
    if not surface:
        return None
    slug = surface.lower().strip()
    return slug if slug in {"hard", "clay", "grass", "carpet"} else None


def normalize_event_start_date(event: Dict[str, Any]) -> Optional[str]:
    candidates = [
        event.get("start_date"),
        event.get("startdate"),
        event.get("start"),
        event.get("date"),
        event.get("event_date"),
        event.get("date_start"),
        event.get("begin_at"),
        event.get("day"),
        event.get("timestamp"),
    ]
    for candidate in candidates:
        normalized = normalize_date(candidate)
        if normalized:
            return normalized
    return None


def normalize_event_name(event: Dict[str, Any]) -> Optional[str]:
    for key in ("name", "event", "tournament", "title", "tournament_name"):
        value = event.get(key)
        if value:
            return str(value)
    return None


def _now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def list_future_events() -> List[Dict[str, Any]]:
    payload = fetch_api("", params={"method": "get_events"})
    events = payload.get("result") or payload.get("events") or payload.get("response") or payload.get("results") or []
    today = dt.date.today()

    future_events: List[Dict[str, Any]] = []
    for event in events:
        start_date = normalize_event_start_date(event)
        if not start_date:
            continue
        try:
            parsed_date = dt.date.fromisoformat(start_date)
        except ValueError:
            continue
        if parsed_date < today:
            continue

        event_id = event.get("event_id") or event.get("id") or event.get("tournament_id")
        name = normalize_event_name(event)
        location_parts = [event.get("city"), event.get("country"), event.get("location"), event.get("venue")]
        location = ", ".join(str(part) for part in location_parts if part)

        future_events.append(
            {
                "external_id": str(event_id) if event_id else None,
                "name": name,
                "category": event.get("category") or event.get("league") or event.get("tour"),
                "surface": event.get("surface"),
                "start_date": start_date,
                "location": location or None,
                "raw_payload": event,
            }
        )

    return future_events


def ensure_source(base_url: str) -> str:
    rows = upsert_rows(
        "ingest_sources",
        [{"slug": SOURCE_SLUG, "name": SOURCE_NAME, "base_url": base_url, "description": "API-Tennis ingestion feed"}],
        "slug",
    )
    return rows[0]["id"]


def ingest_players(source_id: str, tours: Dict[str, Any]) -> Dict[str, int]:
    payload = fetch_api("players")
    players = payload.get("players") or payload.get("response") or []
    normalized: List[Dict[str, Any]] = []
    for player in players:
        tour_slug = normalize_tour_slug(player)
        tour = tours.get(tour_slug) if tour_slug else None
        if not tour:
            continue
        external_id = str(player.get("id") or player.get("player_id") or "")
        if not external_id:
            continue
        country = player.get("country") or {}
        country_code = normalize_country_code(country.get("code") if isinstance(country, dict) else country)
        full_name = player.get("full_name") or " ".join(
            part for part in [player.get("firstname"), player.get("lastname")] if part
        ).strip()
        if not full_name:
            continue

        normalized.append(
            {
                "source_id": source_id,
                "external_id": external_id,
                "tour_id": tour["id"],
                "full_name": full_name,
                "country_code": country_code,
                "handedness": player.get("hand") or player.get("handedness"),
                "birthdate": normalize_date(player.get("birthday") or player.get("birthdate")),
                "raw_payload": player,
                "updated_at": _now_utc(),
            }
        )

    rows = upsert_rows("ingest_players", normalized, "source_id,external_id")
    return {row["external_id"]: row["id"] for row in rows}


def ingest_tournaments(source_id: str, tours: Dict[str, Any], surfaces: Dict[str, Any]) -> None:
    payload = fetch_api("tournaments")
    tournaments = payload.get("tournaments") or payload.get("response") or []
    normalized: List[Dict[str, Any]] = []
    for tournament in tournaments:
        tour_slug = normalize_tour_slug(tournament)
        tour = tours.get(tour_slug) if tour_slug else None
        if not tour:
            continue
        external_id = str(tournament.get("id") or tournament.get("tournament_id") or "")
        if not external_id:
            continue
        surface_slug = normalize_surface_slug(
            tournament.get("surface") or tournament.get("ground") or (tournament.get("court") or {}).get("surface")
        )
        surface = surfaces.get(surface_slug) if surface_slug else None
        season = tournament.get("season") or tournament.get("year")
        name = tournament.get("name") or tournament.get("title")
        if not (season and name):
            continue

        location_parts = [
            tournament.get("city") or (tournament.get("location") or {}).get("city"),
            tournament.get("country") or (tournament.get("location") or {}).get("country"),
        ]
        location = ", ".join(part for part in location_parts if part)

        normalized.append(
            {
                "source_id": source_id,
                "external_id": external_id,
                "tour_id": tour["id"],
                "surface_id": surface.get("id") if surface else None,
                "season": int(season),
                "name": name,
                "location": location or None,
                "category": tournament.get("category") or tournament.get("level"),
                "start_date": normalize_date(tournament.get("start_date") or tournament.get("start")),
                "end_date": normalize_date(tournament.get("end_date") or tournament.get("end")),
                "raw_payload": tournament,
                "updated_at": _now_utc(),
            }
        )

    upsert_rows("ingest_tournaments", normalized, "source_id,external_id")


def ingest_rankings(tours: Dict[str, Any], player_lookup: Dict[str, int]) -> None:
    payload = fetch_api("rankings")
    rankings = payload.get("rankings") or payload.get("response") or []
    normalized: List[Dict[str, Any]] = []
    for row in rankings:
        ranking_info = row.get("ranking") or row
        player_ref = ranking_info.get("player") or row.get("player") or {}
        external_id = str(player_ref.get("id") or player_ref.get("player_id") or row.get("player_id") or "")
        if not external_id:
            continue
        player_id = player_lookup.get(external_id)
        if not player_id:
            continue
        tour_slug = normalize_tour_slug(ranking_info) or normalize_tour_slug(player_ref)
        tour = tours.get(tour_slug) if tour_slug else None
        if not tour:
            continue
        rank_raw = ranking_info.get("rank")
        if rank_raw is None:
            continue
        ranking_date = normalize_date(ranking_info.get("date") or ranking_info.get("ranking_date"))
        if not ranking_date:
            ranking_date = dt.date.today().isoformat()

        normalized.append(
            {
                "player_id": player_id,
                "tour_id": tour["id"],
                "ranking_date": ranking_date,
                "rank": int(rank_raw),
                "points": int(ranking_info.get("points") or 0),
                "raw_payload": row,
                "created_at": _now_utc(),
            }
        )

    upsert_rows("ingest_rankings", normalized, "player_id,ranking_date")


def run_ingestion() -> Dict[str, Any]:
    source_id = ensure_source(require_env(API_BASE_URL, "API_TENNIS_BASE_URL"))
    tours = fetch_lookup_table("tours", "slug")
    surfaces = fetch_lookup_table("surfaces", "slug")
    player_lookup = ingest_players(source_id, tours)
    ingest_tournaments(source_id, tours, surfaces)
    ingest_rankings(tours, player_lookup)
    return {"source_id": source_id, "players_ingested": len(player_lookup)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest API-Tennis data into Supabase.")
    parser.add_argument("--print-summary", action="store_true", help="Print a JSON summary of the ingestion run.")
    parser.add_argument(
        "--list-future-tournaments",
        action="store_true",
        help="Fetch and print future tournaments from the API-Tennis get_events endpoint.",
    )
    args = parser.parse_args()

    if args.list_future_tournaments:
        events = list_future_events()
        print(json.dumps(events, indent=2))
        return

    summary = run_ingestion()
    if args.print_summary:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
