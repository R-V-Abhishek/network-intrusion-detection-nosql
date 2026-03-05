"""Analytics API endpoints for alert aggregation and dashboard views."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from config import UNSW_ATTACK_TYPE_MAPPING

router = APIRouter(prefix="/api", tags=["analytics"])

ALERTS_PATH = Path(os.getenv("ALERTS_PATH", "data/alerts/alerts.jsonl"))


def _parse_timestamp(value: Any) -> datetime | None:
	"""Parse multiple timestamp formats into a timezone-aware UTC datetime."""
	if value is None:
		return None

	if isinstance(value, datetime):
		return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)

	if isinstance(value, (int, float)):
		# Accept seconds or milliseconds epoch values.
		epoch = float(value)
		if epoch > 1e12:
			epoch /= 1000.0
		return datetime.fromtimestamp(epoch, tz=timezone.utc)

	if isinstance(value, str):
		text = value.strip()
		if not text:
			return None
		try:
			return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
		except ValueError:
			return None

	return None


def _normalize_alert(raw: dict[str, Any]) -> dict[str, Any] | None:
	ts = _parse_timestamp(raw.get("timestamp") or raw.get("created_at") or raw.get("event_time"))
	if ts is None:
		return None

	severity = str(raw.get("severity", "unknown")).lower()
	attack_type = str(raw.get("attack_type") or raw.get("attack_cat") or "Unknown")
	session_id = raw.get("session_id")

	return {
		"timestamp": ts,
		"severity": severity,
		"attack_type": attack_type,
		"session_id": None if session_id is None else str(session_id),
		"raw": raw,
	}


def _load_alerts() -> list[dict[str, Any]]:
	"""Load alerts from JSON or JSONL for local/dev dashboard use."""
	if not ALERTS_PATH.exists():
		return []

	rows: list[dict[str, Any]] = []
	text = ALERTS_PATH.read_text(encoding="utf-8").strip()
	if not text:
		return rows

	try:
		parsed = json.loads(text)
		if isinstance(parsed, list):
			rows = [x for x in parsed if isinstance(x, dict)]
		elif isinstance(parsed, dict):
			payload = parsed.get("alerts", [])
			if isinstance(payload, list):
				rows = [x for x in payload if isinstance(x, dict)]
	except json.JSONDecodeError:
		for line in text.splitlines():
			line = line.strip()
			if not line:
				continue
			try:
				obj = json.loads(line)
				if isinstance(obj, dict):
					rows.append(obj)
			except json.JSONDecodeError:
				continue

	normalized = []
	for row in rows:
		item = _normalize_alert(row)
		if item is not None:
			normalized.append(item)
	return normalized


def _filter_window(
	alerts: list[dict[str, Any]],
	hours: int,
	session_id: str | None = None,
) -> list[dict[str, Any]]:
	now = datetime.now(tz=timezone.utc)
	since = now - timedelta(hours=hours)
	output = []
	for alert in alerts:
		if alert["timestamp"] < since:
			continue
		if session_id and alert["session_id"] != session_id:
			continue
		output.append(alert)
	return output


@router.get("/alerts/stats")
def get_alert_stats(
	hours: int = Query(default=24, ge=1, le=168),
	session_id: str | None = Query(default=None),
) -> dict[str, Any]:
	"""Return total alerts and breakdowns by severity and attack type."""
	alerts = _filter_window(_load_alerts(), hours=hours, session_id=session_id)

	by_severity = Counter(item["severity"] for item in alerts)
	by_attack_type = Counter(item["attack_type"] for item in alerts)

	return {
		"window_hours": hours,
		"session_id": session_id,
		"total": len(alerts),
		"by_severity": dict(sorted(by_severity.items())),
		"by_attack_type": dict(sorted(by_attack_type.items())),
	}


@router.get("/alerts/timeline")
def get_alert_timeline(
	hours: int = Query(default=24, ge=1, le=168),
	interval: int = Query(default=60, ge=1, le=1440),
) -> dict[str, Any]:
	"""Return time-bucketed alert counts for charting."""
	alerts = _filter_window(_load_alerts(), hours=hours)
	now = datetime.now(tz=timezone.utc)
	window_start = now - timedelta(hours=hours)

	bucket_size = timedelta(minutes=interval)
	buckets: defaultdict[datetime, int] = defaultdict(int)
	for alert in alerts:
		elapsed = alert["timestamp"] - window_start
		if elapsed.total_seconds() < 0:
			continue
		bucket_index = int(elapsed // bucket_size)
		bucket_start = window_start + (bucket_index * bucket_size)
		buckets[bucket_start] += 1

	points = []
	steps = int((timedelta(hours=hours) // bucket_size) + 1)
	for idx in range(steps):
		bucket_start = window_start + (idx * bucket_size)
		if bucket_start > now:
			break
		points.append(
			{
				"bucket_start": bucket_start.isoformat(),
				"count": buckets.get(bucket_start, 0),
			}
		)

	return {
		"window_hours": hours,
		"interval_minutes": interval,
		"points": points,
	}


@router.get("/attack-types")
def get_attack_types() -> dict[str, Any]:
	"""Return integer-to-label attack type mapping used by UNSW multiclass model."""
	return {"attack_types": UNSW_ATTACK_TYPE_MAPPING}


@router.get("/alerts/by-type/{attack_type}")
def get_alerts_by_type(
	attack_type: str,
	hours: int = Query(default=24, ge=1, le=168),
	session_id: str | None = Query(default=None),
) -> dict[str, Any]:
	"""Return alerts filtered by attack type for drill-down tables."""
	alerts = _filter_window(_load_alerts(), hours=hours, session_id=session_id)
	matching = [
		item
		for item in alerts
		if item["attack_type"].lower() == attack_type.lower()
	]

	if not matching:
		raise HTTPException(status_code=404, detail=f"No alerts found for attack type '{attack_type}'")

	records = []
	for item in sorted(matching, key=lambda x: x["timestamp"], reverse=True):
		row = dict(item["raw"])
		row["timestamp"] = item["timestamp"].isoformat()
		row["severity"] = item["severity"]
		row["attack_type"] = item["attack_type"]
		row["session_id"] = item["session_id"]
		records.append(row)

	return {
		"attack_type": attack_type,
		"window_hours": hours,
		"session_id": session_id,
		"count": len(records),
		"alerts": records,
	}
