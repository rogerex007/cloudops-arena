"""One ordering for participant, instructor and projection scoreboards."""
from datetime import datetime


def timestamp(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,OverflowError):return None


def ranked_teams(rows):
    evidence={}
    for row in rows:
        if row.get('type')!='submission' or row.get('status')!='passed' or int(row.get('points',0))<=0:
            continue
        evidence.setdefault(row.get('team_id'),[]).append(row)
    def order(team):
        score=int(team.get('score',0));records=evidence.get(team.get('team_id'),[])
        times=[timestamp(row.get('answered_at') or row.get('created_at')) for row in records]
        # Unknown historical timing must not beat a verified timestamp. Zero
        # points never get priority merely for registering earlier.
        reached=max(times) if times and all(t is not None for t in times) and sum(int(r['points']) for r in records)==score else float('inf')
        return (-score,reached,str(team.get('team_id') or team.get('SK','')))
    return sorted((row for row in rows if row.get('type')=='team'),key=order)
