"""Server-owned mission deadlines. Legacy events remain untimed until activation."""
import time
from fastapi import HTTPException


def clock(event, now=None):
    now=int(time.time()) if now is None else int(now)
    waiting=event.get('missions_started') is False
    deadline=None if waiting else event.get('mission_deadline')
    remaining=event.get('mission_remaining') if event.get('status')=='paused' else None
    seconds=max(0,int(remaining)) if remaining is not None else max(0,int(deadline)-now) if deadline is not None else None
    return {'server_now':now,'deadline':int(deadline) if deadline is not None else None,
            'remaining_seconds':seconds,'paused':event.get('status')=='paused',
            'waiting':waiting,'closed':waiting or event.get('status')=='finished' or seconds==0}


def require_time(event):
    if event.get('missions_started') is False:raise HTTPException(409,'El instructor todavía no ha iniciado las misiones.')
    if clock(event)['closed']:raise HTTPException(410,'El tiempo de esta misión terminó. Espera la siguiente misión del instructor.')


def deadline_condition():
    return '(attribute_not_exists(mission_deadline) OR mission_deadline > :clock_now)'
