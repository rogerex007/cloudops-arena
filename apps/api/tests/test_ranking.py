from app.ranking import ranked_teams


def team(id,score):return {'type':'team','team_id':id,'score':score}
def passed(id,points,at,**extra):return {'type':'submission','team_id':id,'points':points,'status':'passed','created_at':at,**extra}
def ids(rows):return [t['team_id'] for t in ranked_teams(rows)]


def test_first_to_reach_same_score_wins_and_points_take_priority():
    rows=[team('a',20),team('b',20),team('c',30),passed('a',20,'2026-11-06T10:02:00Z'),passed('b',10,'2026-11-06T10:00:00Z'),passed('b',10,'2026-11-06T10:01:00Z'),passed('c',30,'2026-11-06T10:05:00Z')]
    assert ids(rows)==['c','b','a']
    assert ids(list(reversed(rows)))==['c','b','a']


def test_failed_or_zero_point_retries_never_change_tiebreak():
    rows=[team('a',10),team('b',10),passed('a',10,'2026-11-06T10:00:00Z'),passed('b',10,'2026-11-06T10:01:00Z'),passed('a',0,'2026-11-06T11:00:00Z'),{**passed('a',10,'2026-11-06T12:00:00Z'),'status':'failed'}]
    assert ids(rows)==['a','b']


def test_queue_execution_time_does_not_penalize_earlier_accepted_response():
    rows=[team('a',10),team('b',10),passed('a',10,'2026-11-06T11:00:00Z',answered_at='2026-11-06T10:00:00Z'),passed('b',10,'2026-11-06T10:05:00Z',answered_at='2026-11-06T10:01:00Z')]
    assert ids(rows)==['a','b']


def test_missing_history_and_zero_points_have_stable_order_without_using_signup():
    rows=[team('b',0),team('a',0),team('c',10),team('d',10),passed('d',10,'2026-11-06T10:00:00Z')]
    assert ids(rows)==['d','c','a','b']
