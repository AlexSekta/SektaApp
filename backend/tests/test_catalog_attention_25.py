"""Read-only cross-marketplace review: no automatic association or writes."""
from datetime import datetime, timezone
from types import SimpleNamespace as Row

from backend.services.catalog_dimension_issues_25 import group_snapshot_problems


def master(id=61, article='HS061', dimensions=(7, 7, 24)):
    return Row(id=id, seller_article=article, name='Nemochalka',
               length_cm=dimensions[0], width_cm=dimensions[1], height_cm=dimensions[2])


def snapshot(marketplace='OZON', external_id='439269413', article='HS061', dimensions=(26.2,9.1,10.2), state='OK'):
    return Row(marketplace=marketplace, external_id=external_id, seller_article=article,
               title='Nemochalka Ozon', dimension_state=state,
               length_cm=dimensions[0], width_cm=dimensions[1], height_cm=dimensions[2],
               checked_at=datetime(2026,11,12,tzinfo=timezone.utc))


def test_hs061_preliminary_link_and_dimensions_both_visible():
    issues = group_snapshot_problems([master()], [snapshot()], [], [])
    assert len(issues) == 1
    item = issues[0]
    assert item['master_id'] == 61 and item['confirmed'] is False
    assert [p['code'] for p in item['problems']] == ['LINK_UNCONFIRMED','DIFFERENT']
    assert item['problems'][1]['preliminary'] is True
    assert item['marketplace_cm'] == [26.2,9.1,10.2]


def test_confirmed_link_has_only_dimension_conflict():
    link = Row(marketplace='OZON', external_id='439269413', master_id=61)
    result = group_snapshot_problems([master()], [snapshot()], [link], [])
    assert result[0]['confirmed'] is True
    assert [p['code'] for p in result[0]['problems']] == ['DIFFERENT']
    assert result[0]['problems'][0]['preliminary'] is False


def test_duplicate_article_does_not_attach_to_either_product():
    result = group_snapshot_problems([master(),master(id=62)], [snapshot()], [], [])
    assert result[0]['master_id'] is None
    assert result[0]['problems'][0]['code'] == 'AMBIGUOUS_ARTICLE'
    assert not any(p['code']=='DIFFERENT' for p in result[0]['problems'])


def test_no_article_match_stays_external():
    result = group_snapshot_problems([master()], [snapshot(article='OTHER')], [], [])
    assert result[0]['master_id'] is None
    assert result[0]['problems'][0]['code'] == 'UNMATCHED_CARD'


def test_no_false_missing_on_api_error():
    issues = group_snapshot_problems([master()], [snapshot(state='API_ERROR', dimensions=(None,None,None))], [], [])
    assert [p['code'] for p in issues[0]['problems']] == ['LINK_UNCONFIRMED']


def test_no_issue_when_confirmed_and_dimensions_match():
    link = Row(marketplace='OZON',external_id='439269413',master_id=61)
    issues = group_snapshot_problems([master()], [snapshot(dimensions=(7,7,24))], [link], [])
    assert issues == []


def test_wb_confirmed_is_independent_of_ozon_candidates():
    wb = Row(nm_id='123', master_id=61)
    result = group_snapshot_problems([master()], [snapshot(marketplace='WB',external_id='123', dimensions=(7,7,24)), snapshot()], [], [wb])
    assert len(result) == 1 and result[0]['marketplace'] == 'OZON'
