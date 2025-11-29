# --- DOOR AUTOMATION ---
def auto_check(now_sec, sunrise_sec, sunset_sec, FAILSAFE, FAILSAFE_CLOSED_TO_OPEN, FAILSAFE_OPEN_TO_CLOSED):
    
    OPEN_STATE="open"
    CLOSE_STATE="close"
    
    #open 10 minutes before or after sunrise
    if sunrise_sec - 600 <= now_sec < sunrise_sec + 600:
        return (OPEN_STATE, "Opening door at sunrise")
    #close 10-20 minutes after sunset plus a bit of a buffer if it is before FAILSAFE_OPEN_TO_CLOSED
    elif sunset_sec + 600 <= now_sec < sunset_sec + 1200:
        return (CLOSE_STATE, "Closing door at sunset")
    elif FAILSAFE:
        mod_seconds = now_sec % 86400
        if (FAILSAFE_OPEN_TO_CLOSED <= mod_seconds
            or min(sunrise_sec - 600,FAILSAFE_CLOSED_TO_OPEN == FAILSAFE_CLOSED_TO_OPEN)
            and (mod_seconds < FAILSAFE_CLOSED_TO_OPEN)):
            return (CLOSE_STATE,"[FAILSAFE] Closing door due to time fallback.")
        elif FAILSAFE_CLOSED_TO_OPEN <= mod_seconds < sunset_sec + 600:
            return (OPEN_STATE,"[FAILSAFE] Opening door due to time fallback.")
    else:
        return None
    
if __name__ == "__main__":
    assert auto_check(1000,1000,2000, False, 0, 0) == ("open","Opening door at sunrise")
    assert auto_check(2000,0000,2000, False, 0, 0) == None
    assert auto_check(2600,0000,2000, False, 0000, 3000) == ("close","Closing door at sunset")
    #before sunrise failsafe closed
    assert auto_check(1000,5000,10000, True, 2000, 20000) == ("close","[FAILSAFE] Closing door due to time fallback.")
    #at sunset failsafe closed
    assert auto_check(2000,0000,3000, True, 1000, 2000) == ("close","[FAILSAFE] Closing door due to time fallback.")
    assert auto_check(2000,5000,10000, True, 2000, 20000) == ("open","[FAILSAFE] Opening door due to time fallback.")
    assert auto_check(4000,5000,10000, True, 1000, 20000) == ("open","[FAILSAFE] Opening door due to time fallback.")
