# time_utils.py
import time

def is_dst(t):
    """Determine if DST applies in the US Eastern timezone for the given UTC time tuple."""
    year, month, mday, hour, minute, second, weekday, yearday = t[:8]

    # DST starts at 2:00 AM on the second Sunday in March
    if month > 3 and month < 11:
        return True
    if month < 3 or month > 11:
        return False

    # Find second Sunday in March
    if month == 3:
        first_day = (weekday - ((mday - 1) % 7)) % 7
        second_sunday = 14 - first_day if first_day > 0 else 8
        return mday > second_sunday or (mday == second_sunday and hour >= 2)

    # Find first Sunday in November
    if month == 11:
        first_day = (weekday - ((mday - 1) % 7)) % 7
        first_sunday = 7 - first_day if first_day > 0 else 1
        return mday < first_sunday or (mday == first_sunday and hour < 2)

    return False

def get_est_offset():
    """Returns the offset in seconds for Eastern Time (ET) accounting for DST."""
    t = time.localtime(time.time())
    return -4 * 3600 if is_dst(t) else -5 * 3600

def parse_time(time_str):
  try:
    parts = time_str.split()
    time_part = parts[0]
    ampm_part = parts[1].upper()

    hour, minute, second = map(int, time_part.split(':'))

    if ampm_part == "PM" and hour != 12:
      hour += 12
    elif ampm_part == "AM" and hour == 12:
      hour = 0

    total_seconds = hour * 3600 + minute * 60 + second

    return total_seconds

  except (ValueError, IndexError) as e:
    log(f"parsing {time_str} {e}")
    return None

def today_times(sun_data):
    now = time.localtime()
    date_str = f"{now[0]:04d}-{now[1]:02d}-{now[2]:02d}"

    if date_str not in sun_data:
        return None, None

    sunrise = parse_time(sun_data.get(date_str, {}).get('sunrise', 'N/A'))
    sunset = parse_time(sun_data[date_str]['sunset'])

    return sunrise, sunset

