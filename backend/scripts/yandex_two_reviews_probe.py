"""Read-only Yandex Market review audit. Run: python -m backend.scripts.yandex_two_reviews_probe"""
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.database import SessionLocal
from backend.models.auth import Organization  # noqa: F401
from backend.auth.tenant import (
    legacy_sync_organization_id, set_app_db_role, set_tenant_context,
    clear_tenant_context, reset_app_db_role,
)
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.services.yandex_review_sync import _load_comments

IDS = (465406628, 465409725)


def retrieve(client, business_id, reaction_status):
    found = {}
    token = None
    visited = set()
    pages = 0
    while True:
        data = client.get_goods_feedbacks(
            business_id=business_id, limit=50, page_token=token,
            reaction_status=reaction_status, feedback_ids=list(IDS),
        )
        pages += 1
        result = data.get('result') or {}
        for item in result.get('feedbacks') or []:
            fid = str(item.get('feedbackId') or '')
            if fid in {str(x) for x in IDS}:
                found[fid] = item
        nxt = (result.get('paging') or {}).get('nextPageToken')
        if not nxt or nxt == token:
            break
        if nxt in visited or pages >= 30:
            raise RuntimeError(f'Unexpected pagination on {reaction_status}: {pages} pages')
        visited.add(nxt)
        token = nxt
    return found, pages


def main():
    db = SessionLocal()
    try:
        org_id = legacy_sync_organization_id()
        if org_id is None:
            raise RuntimeError('Organization not found')
        set_app_db_role(db)
        set_tenant_context(db, org_id)
        client = get_yandex_client(db)
        business_id = int(get_yandex_business_id(db, client))
        all_items, pages_all = retrieve(client, business_id, 'ALL')
        need_items, pages_need = retrieve(client, business_id, 'NEED_REACTION')
        output = {
            'checked_at_utc': datetime.now(timezone.utc).isoformat(),
            'business_id': business_id,
            'api_pages': {'ALL': pages_all, 'NEED_REACTION': pages_need},
            'reviews': [],
            'notes': ['Read-only API requests', 'No review texts, personal details or API credentials saved',
                      'A missing review does not prove it was answered'],
        }
        for fid in IDS:
            key = str(fid)
            item = all_items.get(key) or need_items.get(key)
            entry = {
                'feedback_id': key,
                'found_in_all': key in all_items,
                'found_in_need_reaction': key in need_items,
                'need_reaction_flag': item.get('needReaction') if item else None,
                'review_has_text': None,
                'review_has_media': None,
                'review_has_tags': None,
                'comments_count': None,
                'business_comments_count': None,
                'business_comments': [],
                'comments_error': None,
            }
            if item:
                desc = item.get('description') or {}
                media = item.get('media') or {}
                entry['review_has_text'] = any(str(desc.get(k) or '').strip() for k in ('comment', 'advantages', 'disadvantages', 'pros', 'cons'))
                entry['review_has_media'] = bool(media.get('photos') or media.get('videos'))
                entry['review_has_tags'] = bool(desc.get('tags'))
            try:
                comments = _load_comments(client, business_id, fid)
                entry['comments_count'] = len(comments)
                business = [c for c in comments if c.get('author_type') == 'BUSINESS']
                entry['business_comments_count'] = len(business)
                entry['business_comments'] = [
                    {'status': c.get('status'), 'created_at': c['created_at'].isoformat() if c.get('created_at') else None}
                    for c in business
                ]
            except Exception as exc:
                entry['comments_error'] = f'{type(exc).__name__}: {str(exc)[:250]}'
            output['reviews'].append(entry)
            print(f"{key}: ALL={entry['found_in_all']} NEED_REACTION={entry['found_in_need_reaction']} "
                  f"business_comments={entry['business_comments_count']} error={entry['comments_error']}")
        target = Path('yandex_review_diagnostic') / 'two_reviews_status_2026-10-20.json'
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Saved: {target}')
    finally:
        try:
            clear_tenant_context(db)
            reset_app_db_role(db)
        finally:
            db.close()


if __name__ == '__main__':
    main()
