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

from urllib import error, parse, request


API_BASE_URL = os.getenv("API_TENNIS_BASE_URL", "https://api.api-tennis.com/tennis")
API_KEY = os.getenv(
    "API_TENNIS_KEY",
    "db53a535d63fe359cdaa1488d15f3e55e12835c85590c4e3eace0dcc43edb4ab",
)
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
    query = f"?{parse.urlencode(params)}" if params else ""
    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}" + query
    req = request.Request(url, headers={API_KEY_HEADER: api_key})
    try:
        with request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
    except error.HTTPError as exc:
        raise IngestionError(f"API request failed ({exc.code}): {exc.reason}") from exc
    except error.URLError as exc:
        raise IngestionError(f"API request failed: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except ValueError as exc:  # pragma: no cover - defensive
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

    base_url = f"{supabase_url.rstrip('/')}/rest/v1/{path}"
    query = f"?{parse.urlencode(params)}" if params else ""
    url = base_url + query
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            if payload:
                return json.loads(payload)
            return None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise IngestionError(f"Supabase request failed ({exc.code}): {detail}") from exc
    except error.URLError as exc:
        raise IngestionError(f"Supabase request failed: {exc.reason}") from exc


def fetch_lookup_table(table: str, key: str) -> Dict[str, Any]:
    rows = supabase_request("GET", f"{table}", params={"select": "*"})
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
    if len(code) > 3:
        code = code[:3]
    return code


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
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return None
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
    surface_slug = surface.lower().strip()
    if surface_slug in {"hard", "clay", "grass", "carpet"}:
        return surface_slug
    return None


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
    payload = {
        "slug": SOURCE_SLUG,
        "name": SOURCE_NAME,
        "base_url": base_url,
        "description": "API-Tennis ingestion feed",
    }
    rows = upsert_rows("ingest_sources", [payload], "slug")
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
        external_id = str(player.get("id") or player.get("player_id"))
        if not external_id:
            continue
        country = player.get("country") or {}
        country_code = normalize_country_code(country.get("code") if isinstance(country, dict) else country)
        handedness = player.get("hand") or player.get("handedness")
        birthdate = normalize_date(player.get("birthday") or player.get("birthdate"))
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
                "handedness": handedness,
                "birthdate": birthdate,
                "raw_payload": player,
                "updated_at": dt.datetime.utcnow().isoformat(),
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
        external_id = str(tournament.get("id") or tournament.get("tournament_id"))
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
                "updated_at": dt.datetime.utcnow().isoformat(),
            }
        )

    upsert_rows("ingest_tournaments", normalized, "source_id,external_id")


def ingest_rankings(
    tours: Dict[str, Any],
    player_lookup: Dict[str, int],
) -> None:
    payload = fetch_api("rankings")
    rankings = payload.get("rankings") or payload.get("response") or []
    normalized: List[Dict[str, Any]] = []
    for row in rankings:
        ranking_info = row.get("ranking") or row
        player_ref = ranking_info.get("player") or row.get("player") or {}
        external_id = str(player_ref.get("id") or player_ref.get("player_id") or row.get("player_id"))
        if not external_id:
            continue
        player_id = player_lookup.get(external_id)
        if not player_id:
            continue
        tour_slug = normalize_tour_slug(ranking_info) or normalize_tour_slug(player_ref)
        tour = tours.get(tour_slug) if tour_slug else None
        if not tour:
            continue
        ranking_date = normalize_date(ranking_info.get("date") or ranking_info.get("ranking_date"))
        if not ranking_date:
            ranking_date = dt.date.today().isoformat()

        normalized.append(
            {
                "player_id": player_id,
                "tour_id": tour["id"],
                "ranking_date": ranking_date,
                "rank": int(ranking_info.get("rank")),
                "points": int(ranking_info.get("points", 0)),
                "raw_payload": row,
                "created_at": dt.datetime.utcnow().isoformat(),
            }
        )

    upsert_rows("ingest_rankings", normalized, "player_id,ranking_date")


def run_ingestion() -> Dict[str, Any]:
    base_url = require_env(API_BASE_URL, "API_TENNIS_BASE_URL")
    source_id = ensure_source(base_url)
    tours = fetch_lookup_table("tours", "slug")
    surfaces = fetch_lookup_table("surfaces", "slug")

    player_lookup = ingest_players(source_id, tours)
    ingest_tournaments(source_id, tours, surfaces)
    ingest_rankings(tours, player_lookup)

    return {
        "source_id": source_id,
        "players_ingested": len(player_lookup),
    }


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
