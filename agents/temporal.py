"""Publication availability, in New York time. Date-only same-day evidence is uncertain."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo('America/New_York')
# NYSE early closes in the supplied dataset's 2021–2026 coverage.
EARLY_CLOSES = {
    '2021-11-26', '2022-11-25', '2023-07-03', '2023-11-24',
    '2024-07-03', '2024-11-29', '2024-12-24', '2025-07-03',
    '2025-11-28', '2025-12-24', '2026-11-27', '2026-12-24',
}


def close_at(day):
    return datetime.combine(date.fromisoformat(day), time(13 if day in EARLY_CLOSES else 16), EASTERN)


def availability(row, session):
    stamp = row.get('published_at') or row.get('time_et')
    if stamp:
        try:
            dt = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                # Only catalogue time_et explicitly declares the timezone.
                if row.get('time_et') != stamp:
                    return {'temporal_status': 'unknown_timezone', 'eligible_for_explanation': False}
                dt = dt.replace(tzinfo=EASTERN)
            local = dt.astimezone(EASTERN)
            late = local > close_at(session)
            return {'published_at_et': local.isoformat(), 'temporal_status': 'after_close' if late else 'before_close',
                    'eligible_for_explanation': not late, 'after_session': late}
        except (ValueError, TypeError):
            return {'temporal_status': 'invalid_timestamp', 'eligible_for_explanation': False}
    try:
        day = date.fromisoformat(str(row.get('published_date', '')))
        target = date.fromisoformat(session)
    except (ValueError, TypeError):
        return {'temporal_status': 'missing_date', 'eligible_for_explanation': False}
    return {'temporal_status': 'date_only_prior' if day < target else 'same_day_time_unknown' if day == target else 'after_close',
            'eligible_for_explanation': day < target, 'after_session': day > target}


def contemporaneous(row, session=None):
    return availability(row, session or row.get('session', ''))['eligible_for_explanation']


def annotate(row):
    return {**row, **availability(row, row.get('session', ''))}
