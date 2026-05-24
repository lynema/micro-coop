def auto_check(
    now_sec,
    sunrise_sec,
    sunset_sec,
    FAILSAFE,
    MAX_CLOSED_TO_OPEN,
    MAX_OPEN_TO_CLOSED
):

    OPEN_STATE = "open"
    CLOSE_STATE = "close"

    OPENING_MSG = "Opening door"
    CLOSING_MSG = "Closing door"

    FAILSAFE_DAYTIME_MSG = "[FAILSAFE] Keeping door open during scheduled daytime"

    FAILSAFE_NIGHTTIME_MSG = "[FAILSAFE] Keeping door closed during scheduled nighttime"

    mod_seconds = now_sec % 86400

    effective_open = (
        min(sunrise_sec, MAX_CLOSED_TO_OPEN)
        if FAILSAFE else sunrise_sec
    )

    effective_close = (
        min(sunset_sec, MAX_OPEN_TO_CLOSED)
        if FAILSAFE else sunset_sec
    )

    open_window = (
        effective_open - 600 <= mod_seconds < effective_open + 600
    )

    close_window = (
        effective_close + 600 <= mod_seconds < effective_close + 1200
    )

    daytime = (
        effective_open + 600 <= mod_seconds < effective_close + 600
    )

    if open_window:
        return (OPEN_STATE, OPENING_MSG)

    elif close_window:
        return (CLOSE_STATE, CLOSING_MSG)

    elif not FAILSAFE:
        return None

    elif daytime:
        return (OPEN_STATE, FAILSAFE_DAYTIME_MSG)

    return (CLOSE_STATE, FAILSAFE_NIGHTTIME_MSG)


if __name__ == "__main__":

    # now_sec,sunrise_sec,sunset_sec,
    # FAILSAFE,MAX_CLOSED_TO_OPEN,MAX_OPEN_TO_CLOSED

    # ------------------------------------------------------------
    # BASIC SUNRISE OPEN
    # ------------------------------------------------------------

    print(auto_check(1000, 1000, 2000, False, 0, 0))
    assert auto_check(
        1000, 1000, 2000,
        False, 0, 0
    ) == ("open", "Opening door")


    # ------------------------------------------------------------
    # BASIC SUNSET CLOSE
    # ------------------------------------------------------------

    print(auto_check(2600, 0, 2000, False, 0, 3000))
    assert auto_check(
        2600, 0, 2000,
        False, 0, 3000
    ) == ("close", "Closing door")

    # ------------------------------------------------------------
    # FAILSAFE EARLIER OPEN TIME WINS
    # ------------------------------------------------------------

    print(auto_check(1400, 5000, 10000, True, 1000, 20000))

    assert auto_check(
        1200, 5000, 10000,
        True, 1000, 20000
    ) == (
        "open",
        "Opening door"
    )

    # ------------------------------------------------------------
    # FAILSAFE NIGHTTIME CLOSED
    # ------------------------------------------------------------

    print(auto_check(1000, 5000, 10000, True, 2000, 20000))
    assert auto_check(
        1000, 5000, 10000,
        True, 2000, 20000
    ) == (
        "close",
        "[FAILSAFE] Keeping door closed during scheduled nighttime"
    )

    # ------------------------------------------------------------
    # FAILSAFE DAYTIME STATE
    # ------------------------------------------------------------

    print(auto_check(7000, 5000, 10000, True, 2000, 20000))
    assert auto_check(
        7000, 5000, 10000,
        True, 2000, 20000
    ) == (
        "open",
        "[FAILSAFE] Keeping door open during scheduled daytime"
    )

    # ------------------------------------------------------------
    # FAILSAFE EARLIER OPEN TIME WINS
    # ------------------------------------------------------------

    print(auto_check(2000, 5000, 10000, True, 1000, 20000))
    assert auto_check(
        1400, 5000, 10000,
        True, 1000, 20000
    ) == (
        "open",
        "Opening door"
    )

    # ------------------------------------------------------------
    # FAILSAFE EARLIER CLOSE TIME WINS
    # ------------------------------------------------------------

    print(auto_check(2600, 0, 5000, True, 0, 2000))
    assert auto_check(
        2600, 0, 5000,
        True, 0, 2000
    ) == (
        "close",
        "Closing door"
    )

    # ------------------------------------------------------------
    # REGRESSION:
    # sunrise open should NOT re-close before failsafe open
    # ------------------------------------------------------------

    print(auto_check(
        6*3600 + 23*60,
        5*3600 + 54*60,
        20*3600,
        True,
        7*3600,
        21*3600
    ))

    assert auto_check(
        6*3600 + 23*60,
        5*3600 + 54*60,
        20*3600,
        True,
        7*3600,
        21*3600
    ) == (
        "open",
        "[FAILSAFE] Keeping door open during scheduled daytime"
    )

    # ------------------------------------------------------------
    # EXACT OPEN WINDOW LOWER BOUNDARY
    # ------------------------------------------------------------

    print(auto_check(4400, 5000, 10000, False, 0, 0))
    assert auto_check(
        4400, 5000, 10000,
        False, 0, 0
    ) == (
        "open",
        "Opening door"
    )

    # ------------------------------------------------------------
    # EXACT CLOSE WINDOW LOWER BOUNDARY
    # ------------------------------------------------------------

    print(auto_check(10600, 5000, 10000, False, 0, 0))
    assert auto_check(
        10600, 5000, 10000,
        False, 0, 0
    ) == (
        "close",
        "Closing door"
    )
    
    # ------------------------------------------------------------
    # NONE WHEN NO FAILSAFE AND OUTSIDE NORMAL WINDOWS FOR RISE/SET
    # ------------------------------------------------------------
    
    assert auto_check(
        2000, 0, 2000,
        False, 0, 0
    ) == None

    assert auto_check(
        50000, 5000, 10000,
        False, 0, 0
    ) == None

    print("All tests passed.")