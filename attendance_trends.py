"""Comparable monthly attendance, with missing/future months kept as gaps."""
def average_academic_series(totals, recorded_days):
    return {status: [round(value / days, 1) if days else None
                     for value, days in zip(values, recorded_days)]
            for status, values in totals.items()}
