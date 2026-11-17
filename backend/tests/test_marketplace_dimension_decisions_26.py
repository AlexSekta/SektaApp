"""Patch 26: decisions never alter source data and stale reviews reopen."""
from datetime import datetime, timezone
from types import SimpleNamespace as Row
from backend.services.catalog_dimension_issues_25 import group_snapshot_problems


def fixture(dimensions=(26.2, 9.1, 10.2), confirmed=True):
    master = Row(id=61, seller_article='HS061', name='Nemochalka', length_cm=7, width_cm=7, height_cm=24)
    snapshot = Row(marketplace='OZON', external_id='439269413', seller_article='HS061', title='Ozon',
                   length_cm=dimensions[0], width_cm=dimensions[1], height_cm=dimensions[2],
                   dimension_state='OK', checked_at=datetime.now(timezone.utc))
    links = [Row(marketplace='OZON', external_id='439269413', master_id=61)] if confirmed else []
    return master, snapshot, links


def problems(decisions=(), dimensions=(26.2, 9.1, 10.2), confirmed=True):
    m, s, links = fixture(dimensions, confirmed)
    return group_snapshot_problems([m], [s], links, [], decisions)


def test_confirmed_fingerprint_attached_only_to_dimensions():
    row = problems()[0]
    assert row['confirmed'] is True
    assert [x['code'] for x in row['problems']] == ['DIFFERENT']
    assert len(row['problems'][0]['fingerprint']) == 64


def test_unconfirmed_cannot_have_review_fingerprint():
    row = problems(confirmed=False)[0]
    assert [x['code'] for x in row['problems']] == ['LINK_UNCONFIRMED', 'DIFFERENT']
    assert 'fingerprint' not in row['problems'][1]


def test_disputed_stays_visible_with_status():
    issue = problems()[0]['problems'][0]
    decision = Row(id=1, marketplace='OZON', external_id='439269413', master_id=61,
                   issue_code='DIFFERENT', fingerprint=issue['fingerprint'], decision='DISPUTED')
    result = problems([decision])
    assert result[0]['problems'][0]['decision'] == 'DISPUTED'


def test_acceptance_suppresses_same_difference_only():
    issue = problems()[0]['problems'][0]
    decision = Row(id=1, marketplace='OZON', external_id='439269413', master_id=61,
                   issue_code='DIFFERENT', fingerprint=issue['fingerprint'], decision='ACCEPTED')
    assert problems([decision]) == []
    assert problems([decision], (26.3, 9.1, 10.2))[0]['problems'][0]['code'] == 'DIFFERENT'


def test_latest_decision_wins_for_same_values():
    issue = problems()[0]['problems'][0]
    first = Row(id=1, marketplace='OZON', external_id='439269413', master_id=61,
                issue_code='DIFFERENT', fingerprint=issue['fingerprint'], decision='ACCEPTED')
    second = Row(id=2, marketplace='OZON', external_id='439269413', master_id=61,
                 issue_code='DIFFERENT', fingerprint=issue['fingerprint'], decision='DISPUTED')
    assert problems([second, first])[0]['problems'][0]['decision'] == 'DISPUTED'
