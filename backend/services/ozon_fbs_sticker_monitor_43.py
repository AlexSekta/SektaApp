"""Ozon FBS archive: three independent, opt-in listing/identifier/PDF workers.

Only reads postings and requests printable labels, NEVER packs or ships orders.
All archival state is persisted in PostgreSQL; failures do not drop queued work.
"""
import hashlib
import ipaddress
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from sqlalchemy import text
from backend.database import SessionLocal, engine
from backend.auth.tenant import (
    legacy_sync_organization_id, set_app_db_role, set_tenant_context,
    clear_tenant_context, reset_app_db_role,
)
from backend.logging_config import get_logger
from backend.services.marketplace_clients import get_ozon_client

log = get_logger('ozon_fbs_sticker_monitor')
STOP = threading.Event()
STARTED = False
_API_LOCK = threading.Lock()
_NEXT_API_CALL = 0.0
MOSCOW = timezone(timedelta(hours=3))
INTERVAL = max(30, int(os.getenv('OZON_FBS_STICKER_INTERVAL_SECONDS', '60')))
LOOKBACK_DAYS = max(1, min(14, int(os.getenv('OZON_FBS_STICKER_LOOKBACK_DAYS', '1'))))
MAX_ACTIONS = max(1, min(20, int(os.getenv('OZON_FBS_STICKER_ACTIONS_PER_CYCLE', '8'))))
MAX_BYTES = 8 * 1024 * 1024
PDF_ENABLED = os.getenv('OZON_FBS_PDF_ENABLED', 'false').lower() in ('1', 'true', 'yes')
DETAILS_PER_CYCLE = max(1, min(30, int(os.getenv('OZON_FBS_SCANIT_PER_CYCLE', '8'))))
LIST_INTERVAL = max(60, int(os.getenv('OZON_FBS_LIST_INTERVAL_SECONDS', str(INTERVAL))))
SCANIT_INTERVAL = max(30, int(os.getenv('OZON_FBS_SCANIT_INTERVAL_SECONDS', '60')))
PDF_INTERVAL = max(60, int(os.getenv('OZON_FBS_PDF_INTERVAL_SECONDS', '120')))
# PDF flow is opt-in; start with at most two jobs per cycle to avoid API bursts.
PDF_ACTIONS = max(1, min(8, int(os.getenv('OZON_FBS_PDF_ACTIONS_PER_CYCLE', '2'))))
API_GAP = max(0.2, float(os.getenv('OZON_FBS_API_MIN_GAP_SECONDS', '0.8')))


def paced(call):
    """Serialize this monitor's API requests across the three workers."""
    global _NEXT_API_CALL
    with _API_LOCK:
        delay = max(0.0, _NEXT_API_CALL - time.monotonic())
        if delay and STOP.wait(delay):
            raise RuntimeError('Ozon FBS monitor stopped')
        _NEXT_API_CALL = time.monotonic() + API_GAP
    return call()



def ensure_schema():
    with engine.begin() as conn:
        conn.execute(text('''CREATE TABLE IF NOT EXISTS ozon_fbs_sticker_archive (
            id BIGSERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            posting_number VARCHAR(100) NOT NULL,
            order_number VARCHAR(100),
            status VARCHAR(100),
            scanit VARCHAR(200),
            upper_barcode VARCHAR(200),
            lower_barcode VARCHAR(200),
            scanit_checked_at TIMESTAMPTZ,
            scanit_next_attempt_at TIMESTAMPTZ,
            scanit_attempts INTEGER NOT NULL DEFAULT 0,
            scanit_error VARCHAR(200),
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ozon_created_at TIMESTAMPTZ,
            ready_detected_at TIMESTAMPTZ,
            ready_from_new BOOLEAN NOT NULL DEFAULT false,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            label_task_id BIGINT,
            label_task_type VARCHAR(50),
            label_requested_at TIMESTAMPTZ,
            label_next_attempt_at TIMESTAMPTZ,
            label_attempts INTEGER NOT NULL DEFAULT 0,
            label_error VARCHAR(200),
            sticker_pdf BYTEA,
            sticker_sha256 CHAR(64),
            sticker_saved_at TIMESTAMPTZ,
            CONSTRAINT uq_ozon_fbs_archive_org_posting UNIQUE(organization_id,posting_number)
        )'''))
        for col in (
            'upper_barcode VARCHAR(200)', 'lower_barcode VARCHAR(200)',
            'scanit_checked_at TIMESTAMPTZ', 'scanit_next_attempt_at TIMESTAMPTZ',
            'scanit_attempts INTEGER NOT NULL DEFAULT 0', 'scanit_error VARCHAR(200)',
            'ozon_created_at TIMESTAMPTZ', 'ready_detected_at TIMESTAMPTZ',
            'ready_from_new BOOLEAN NOT NULL DEFAULT false'
        ):
            conn.execute(text('ALTER TABLE ozon_fbs_sticker_archive ADD COLUMN IF NOT EXISTS ' + col))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS ozon_fbs_label_settings (
            organization_id INTEGER PRIMARY KEY,
            delay_minutes INTEGER NOT NULL DEFAULT 20 CHECK (delay_minutes BETWEEN 5 AND 1440),
            auto_create_enabled BOOLEAN NOT NULL DEFAULT false,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )'''))
        conn.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ozon_fbs_label_settings TO marketplace_app'))
        conn.execute(text('ALTER TABLE ozon_fbs_label_settings ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE ozon_fbs_label_settings FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON ozon_fbs_label_settings'))
        conn.execute(text('''CREATE POLICY tenant_isolation ON ozon_fbs_label_settings
            USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
            WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)'''))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_ozon_fbs_scanit_pending ON ozon_fbs_sticker_archive (organization_id, scanit_next_attempt_at, first_seen_at)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_ozon_fbs_archive_pending ON ozon_fbs_sticker_archive (organization_id, sticker_saved_at, label_next_attempt_at)'))
        conn.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ozon_fbs_sticker_archive TO marketplace_app'))
        conn.execute(text('GRANT USAGE,SELECT,UPDATE ON SEQUENCE ozon_fbs_sticker_archive_id_seq TO marketplace_app'))
        conn.execute(text('ALTER TABLE ozon_fbs_sticker_archive ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE ozon_fbs_sticker_archive FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON ozon_fbs_sticker_archive'))
        conn.execute(text('''CREATE POLICY tenant_isolation ON ozon_fbs_sticker_archive
           USING (organization_id = current_setting('app.organization_id', true)::integer)
           WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)'''))


def normalize_list(body):
    """Support current v4 response and old nested result without inventing missing fields."""
    if not isinstance(body, dict):
        raise ValueError('Unexpected Ozon list response')
    data = body.get('result') if isinstance(body.get('result'), dict) else body
    postings = data.get('postings')
    if not isinstance(postings, list):
        raise ValueError('Ozon list missing postings array')
    return postings, bool(data.get('has_next')), data.get('cursor')


def parse_task(body):
    if not isinstance(body, dict):
        raise ValueError('Invalid Ozon label creation response')
    tasks = body.get('tasks') or (body.get('result') or {}).get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('Ozon label task list missing')
    selected = next((t for t in tasks if t.get('task_type') == 'small_label'), tasks[0])
    task = int(selected['task_id'])
    if task < 1:
        raise ValueError('Invalid Ozon label task id')
    return task, str(selected.get('task_type') or '')


def parse_task_status(body):
    if not isinstance(body, dict):
        raise ValueError('Invalid Ozon label get response')
    data = body.get('result') if isinstance(body.get('result'), dict) else body
    status = data.get('status')
    if isinstance(status, dict):
        # New API puts code and unprinted_postings in status object.
        code = str(status.get('code') or '').lower()
        unprinted = status.get('unprinted_postings') or []
    else:
        code = str(status or '').lower()
        unprinted = data.get('unprinted_postings') or []
    if code in ('completed', 'done'):
        if unprinted:
            raise ValueError('Ozon label generation skipped the posting')
        if not data.get('file_url'):
            raise ValueError('Completed Ozon task has no PDF URL')
        return 'completed', str(data['file_url'])
    if code in ('pending', 'in_progress', 'processing', 'created'):
        return 'pending', None
    if code in ('error', 'failed') or data.get('error'):
        raise ValueError('Ozon label task failed')
    raise ValueError('Unexpected Ozon label task status')


def allowed_pdf_url(url):
    """Do not request arbitrary endpoints supplied as a file_url."""
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower().rstrip('.')
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    configured = [x.strip().lower().lstrip('.') for x in os.getenv('OZON_FBS_LABEL_HOST_SUFFIXES', 'ozon.ru,ozonusercontent.com,ozoncdn.com,ir.ozone.ru').split(',') if x.strip()]
    return any(host == suffix or host.endswith('.' + suffix) for suffix in configured)


def download_pdf(url):
    if not allowed_pdf_url(url):
        raise ValueError('PDF host is not allowlisted; check OZON_FBS_LABEL_HOST_SUFFIXES')
    response = requests.get(url, timeout=(10, 30), allow_redirects=False, stream=True)
    try:
        if response.status_code != 200:
            raise ValueError(f'PDF download HTTP {response.status_code}')
        data = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ValueError('PDF exceeds 8 MiB')
        if not data.startswith(b'%PDF-'):
            raise ValueError('Downloaded file is not a PDF')
        return bytes(data)
    finally:
        response.close()


def list_recent(client, on_page=None):
    end = datetime.now(timezone.utc) + timedelta(minutes=2)
    begin = end - timedelta(days=LOOKBACK_DAYS)
    since, to = begin.isoformat(timespec='seconds'), end.isoformat(timespec='seconds')
    cursor = ''
    seen = set()
    result = {}
    for _ in range(20):
        from backend.services.ozon_order_sync import retry_ozon_request
        response = retry_ozon_request(
            lambda: paced(lambda: client.list_fbs_postings_raw(since=since, to=to, cursor=cursor, limit=100)),
            scheme='fbs', operation='sticker_monitor_listing')
        if response.get('status_code') != 200:
            raise RuntimeError(f'Ozon list HTTP {response.get("status_code")}')
        postings, has_next, next_cursor = normalize_list(response.get('body'))
        if on_page and postings:
            on_page({str(p['posting_number']):p for p in postings if isinstance(p, dict) and p.get('posting_number')})
        for posting in postings:
            number = posting.get('posting_number')
            if number:
                result[str(number)] = posting
        if not has_next:
            return result
        if not next_cursor or str(next_cursor) in seen:
            raise RuntimeError('Ozon list cursor repeated/absent')
        cursor = str(next_cursor)
        seen.add(cursor)
    raise RuntimeError('Ozon FBS listing page cap reached')


def parse_ozon_created(value):
    """Convert an API timestamp; never use first-seen as a fabricated creation time."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def persist_postings(db, org, postings):
    for number, item in postings.items():
        status = str(item.get('status') or '')
        db.execute(text("""INSERT INTO ozon_fbs_sticker_archive
              (organization_id,posting_number,order_number,status,scanit,ozon_created_at)
              VALUES (:org,:no,:order,:status,:scanit,:created)
              ON CONFLICT (organization_id,posting_number) DO UPDATE SET
              ready_detected_at=CASE
                WHEN ozon_fbs_sticker_archive.status IN ('awaiting_packaging','awaiting_registration','acceptance_in_progress')
                  AND EXCLUDED.status='awaiting_deliver'
                  AND ozon_fbs_sticker_archive.ready_detected_at IS NULL
                THEN now() ELSE ozon_fbs_sticker_archive.ready_detected_at END,
              ready_from_new=CASE
                WHEN ozon_fbs_sticker_archive.status IN ('awaiting_packaging','awaiting_registration','acceptance_in_progress')
                  AND EXCLUDED.status='awaiting_deliver'
                THEN true ELSE ozon_fbs_sticker_archive.ready_from_new END,
              order_number=COALESCE(NULLIF(EXCLUDED.order_number,''),ozon_fbs_sticker_archive.order_number),
              status=EXCLUDED.status,
              scanit=COALESCE(NULLIF(EXCLUDED.scanit,''),ozon_fbs_sticker_archive.scanit),
              ozon_created_at=COALESCE(ozon_fbs_sticker_archive.ozon_created_at,EXCLUDED.ozon_created_at),
              last_seen_at=now()"""), {
            'org': org, 'no': number, 'order': str(item.get('order_number') or ''),
            'status': status, 'scanit': str(item.get('scanit') or ''),
            'created': parse_ozon_created(item.get('created_at')),
        })
    db.commit()


def parse_detail_identifiers(body, expected_posting):
    # Only accept identifiers for the requested posting.
    if not isinstance(body, dict):
        raise ValueError('Invalid Ozon detail response')
    data = body.get('result') if isinstance(body.get('result'), dict) else body
    actual = str(data.get('posting_number') or '')
    if actual != expected_posting:
        raise ValueError('Posting mismatch in Ozon detail response')
    codes = data.get('barcodes') or {}
    if not isinstance(codes, dict):
        raise ValueError('Invalid barcodes response')
    return {
        'posting_number': actual,
        'order_number': str(data.get('order_number') or ''),
        'status': str(data.get('status') or ''),
        'scanit': str(data.get('scanit') or '').strip(),
        'upper_barcode': str(codes.get('upper_barcode') or '').strip(),
        'lower_barcode': str(codes.get('lower_barcode') or '').strip(),
    }


def detail_posting(client, number):
    # Read-only request.
    from backend.services.ozon_order_sync import retry_ozon_request
    reply = retry_ozon_request(
        lambda: paced(lambda: client.post_raw('/v3/posting/fbs/get', {
            'posting_number': number,
            'with': {'barcodes': True, 'analytics_data': False, 'financial_data': False}
        })), scheme='fbs', operation='sticker_identifier_get', posting_number=number)
    return parse_detail_identifiers(reply.get('body'), number)


def save_identifiers(db, org, item):
    # Atomic idempotent upsert.
    db.execute(text('''INSERT INTO ozon_fbs_sticker_archive
        (organization_id, posting_number, order_number, status, scanit,
         upper_barcode, lower_barcode, scanit_checked_at)
        VALUES (:org,:no,:order,:status,:scanit,:upper,:lower,now())
        ON CONFLICT (organization_id,posting_number) DO UPDATE SET
          order_number=COALESCE(NULLIF(EXCLUDED.order_number,''),ozon_fbs_sticker_archive.order_number),
          ready_detected_at=CASE
            WHEN ozon_fbs_sticker_archive.status IN ('awaiting_packaging','awaiting_registration','acceptance_in_progress')
              AND EXCLUDED.status='awaiting_deliver'
              AND ozon_fbs_sticker_archive.ready_detected_at IS NULL
            THEN now() ELSE ozon_fbs_sticker_archive.ready_detected_at END,
          ready_from_new=CASE
            WHEN ozon_fbs_sticker_archive.status IN ('awaiting_packaging','awaiting_registration','acceptance_in_progress')
              AND EXCLUDED.status='awaiting_deliver'
            THEN true ELSE ozon_fbs_sticker_archive.ready_from_new END,
          status=COALESCE(NULLIF(EXCLUDED.status,''),ozon_fbs_sticker_archive.status),
          scanit=COALESCE(NULLIF(ozon_fbs_sticker_archive.scanit,''),NULLIF(EXCLUDED.scanit,'')),
          upper_barcode=COALESCE(NULLIF(ozon_fbs_sticker_archive.upper_barcode,''),NULLIF(EXCLUDED.upper_barcode,'')),
          lower_barcode=COALESCE(NULLIF(ozon_fbs_sticker_archive.lower_barcode,''),NULLIF(EXCLUDED.lower_barcode,'')),
          scanit_checked_at=now(), scanit_next_attempt_at=NULL, scanit_error=NULL,
          last_seen_at=now()'''), {
        'org':org, 'no':item['posting_number'], 'order':item['order_number'],
        'status':item['status'], 'scanit':item['scanit'],
        'upper':item['upper_barcode'], 'lower':item['lower_barcode']})
    db.commit()


def scanit_backoff(db, org, number, error):
    db.execute(text('''UPDATE ozon_fbs_sticker_archive SET
        scanit_attempts=scanit_attempts+1,
        scanit_error=:error,
        scanit_next_attempt_at=now()+make_interval(secs => LEAST(3600, 60 * power(2,LEAST(scanit_attempts,6))))
        WHERE organization_id=:org AND posting_number=:no'''),
        {'org':org,'no':number,'error':str(error)[:200]})
    db.commit()


def collect_missing_identifiers(db, org, client, limit=DETAILS_PER_CYCLE):
    # Independent durable queue.
    rows = db.execute(text('''SELECT posting_number FROM ozon_fbs_sticker_archive
        WHERE organization_id=:org AND (scanit IS NULL OR scanit='')
          AND (scanit_next_attempt_at IS NULL OR scanit_next_attempt_at<=now())
        ORDER BY first_seen_at DESC LIMIT :limit'''),
        {'org':org,'limit':limit}).mappings().all()
    saved = 0
    for row in rows:
        if STOP.is_set():
            break
        number = row['posting_number']
        try:
            data = detail_posting(client, number)
            if not data['scanit']:
                raise ValueError('scanit not yet available')
            save_identifiers(db, org, data)
            saved += 1
            log.info('OZON_FBS_SCANIT_SAVED org=%s posting=%s',org,number)
        except Exception as exc:
            db.rollback()
            scanit_backoff(db,org,number,type(exc).__name__)
            log.warning('OZON_FBS_SCANIT_RETRY org=%s posting=%s type=%s',org,number,type(exc).__name__)
        STOP.wait(0.3)
    return saved


def backoff(db, org, number, message):
    db.execute(text('''UPDATE ozon_fbs_sticker_archive
      SET label_attempts=label_attempts+1,
          label_error=:error,
          label_next_attempt_at=now()+make_interval(secs => LEAST(1800, 30 * power(2,LEAST(label_attempts,6))))
      WHERE organization_id=:org AND posting_number=:no'''),
      {'org': org, 'no': number, 'error': str(message)[:200]})
    db.commit()


def process_one(db, org, client, posting):
    number = posting['posting_number']
    task_id = posting['label_task_id']
    if task_id is None:
        # Must be a confirmed new -> awaiting_deliver transition, not historical data.
        if not posting.get('eligible_create'):
            log.info('OZON_FBS_PDF_SKIP_NO_TASK org=%s posting=%s', org, number)
            return
        # One-way guard BEFORE network request: ambiguous network failures must not
        # trigger repeated create calls. Manual inspection is required on failures.
        claimed = db.execute(text("""UPDATE ozon_fbs_sticker_archive
            SET label_requested_at=now(), label_error='create_requested_unconfirmed',
                label_next_attempt_at=NULL
            WHERE organization_id=:org AND posting_number=:no
              AND label_task_id IS NULL AND label_requested_at IS NULL
              AND ready_from_new=true AND status='awaiting_deliver'
              AND ready_detected_at IS NOT NULL
              AND EXISTS (SELECT 1 FROM ozon_fbs_label_settings settings
                WHERE settings.organization_id=:org AND settings.auto_create_enabled=true
                AND ready_detected_at + make_interval(mins => settings.delay_minutes) <= now())
            RETURNING posting_number"""), {'org':org,'no':number}).first()
        db.commit()
        if not claimed:
            return
        try:
            reply = paced(lambda: client.post_raw('/v3/posting/fbs/package-label/create',
                            {'posting_numbers':[number]}))
            if reply.get('status_code') != 200:
                raise RuntimeError(f'label create HTTP {reply.get("status_code")}')
            task_id, task_type = parse_task(reply.get('body'))
        except Exception:
            # Leave label_requested_at set; never blindly retry creation.
            log.warning('OZON_FBS_LABEL_CREATE_UNCONFIRMED org=%s posting=%s',org,number)
            raise
        db.execute(text("""UPDATE ozon_fbs_sticker_archive SET
             label_task_id=:task, label_task_type=:type, label_error=NULL,
             label_next_attempt_at=now()+interval '20 seconds'
             WHERE organization_id=:org AND posting_number=:no"""),
             {'task':task_id,'type':task_type,'org':org,'no':number})
        db.commit()
        log.info('OZON_FBS_LABEL_TASK_CREATED_AFTER_DELAY org=%s posting=%s',org,number)
        return
    reply = paced(lambda: client.post_raw('/v2/posting/fbs/package-label/get', {'task_id': int(task_id)}))
    if reply.get('status_code') != 200:
        raise RuntimeError(f'label get HTTP {reply.get("status_code")}')
    state, url = parse_task_status(reply.get('body'))
    if state != 'completed':
        db.execute(text("""UPDATE ozon_fbs_sticker_archive SET
            label_next_attempt_at=now()+interval '30 seconds'
            WHERE organization_id=:org AND posting_number=:no"""), {'org':org,'no':number})
        db.commit()
        return
    pdf = download_pdf(url)
    digest = hashlib.sha256(pdf).hexdigest()
    result = db.execute(text("""UPDATE ozon_fbs_sticker_archive SET
        sticker_pdf=:pdf, sticker_sha256=:hash, sticker_saved_at=now(),
        label_error=NULL, label_next_attempt_at=NULL
        WHERE organization_id=:org AND posting_number=:no AND sticker_pdf IS NULL"""),
        {'pdf':pdf,'hash':digest,'org':org,'no':number})
    db.commit()
    if result.rowcount == 1:
        log.info('OZON_FBS_STICKER_SAVED org=%s posting=%s bytes=%s sha256=%s', org,number,len(pdf),digest)


def _db_session():
    org = legacy_sync_organization_id()
    if org is None:
        return None, None
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, org)
    except Exception:
        db.rollback()
        db.close()
        raise
    return db, org


def _close_session(db):
    if db is None:
        return
    try:
        db.rollback()
        clear_tenant_context(db)
        reset_app_db_role(db)
    finally:
        db.close()


def listing_cycle():
    db, org = _db_session()
    if db is None:
        return
    try:
        client = get_ozon_client(db)
        # Each page is committed independently: HTTP failure or a page cap
        # cannot discard successfully fetched postings.
        items = list_recent(client, on_page=lambda page: persist_postings(db, org, page))
        log.info('OZON_FBS_MONITOR_LIST_OK org=%s postings=%s', org, len(items))
    finally:
        _close_session(db)


def identifiers_cycle():
    db, org = _db_session()
    if db is None:
        return
    try:
        found = collect_missing_identifiers(db, org, get_ozon_client(db))
        log.info('OZON_FBS_MONITOR_SCANIT_OK org=%s saved=%s', org, found)
    finally:
        _close_session(db)


def pdf_candidates(db, org, limit):
    """Prefer known tasks. Creating new ones requires explicit per-org opt-in."""
    return db.execute(text("""SELECT a.posting_number, a.label_task_id,
      (a.label_task_id IS NULL AND COALESCE(s.auto_create_enabled,false)
       AND a.ready_from_new=true AND a.status='awaiting_deliver'
       AND a.ready_detected_at IS NOT NULL
       AND a.ready_detected_at + make_interval(mins => COALESCE(s.delay_minutes,20)) <= now()
       AND a.label_requested_at IS NULL) AS eligible_create
      FROM ozon_fbs_sticker_archive a
      LEFT JOIN ozon_fbs_label_settings s ON s.organization_id=a.organization_id
      WHERE a.organization_id=:org AND a.sticker_pdf IS NULL
        AND NULLIF(a.scanit,'') IS NOT NULL
        AND (a.label_next_attempt_at IS NULL OR a.label_next_attempt_at<=now())
        AND (a.label_task_id IS NOT NULL OR
           (COALESCE(s.auto_create_enabled,false) AND a.ready_from_new=true
            AND a.status='awaiting_deliver' AND a.ready_detected_at IS NOT NULL
            AND a.ready_detected_at + make_interval(mins => COALESCE(s.delay_minutes,20)) <= now()
            AND a.label_requested_at IS NULL))
      ORDER BY (a.label_task_id IS NOT NULL) DESC, a.first_seen_at DESC
      LIMIT :limit"""), {'org':org,'limit':limit}).mappings().all()


def pdf_cycle():
    if not PDF_ENABLED:
        return
    db, org = _db_session()
    if db is None:
        return
    try:
        client = get_ozon_client(db)
        rows = pdf_candidates(db, org, PDF_ACTIONS)
        for item in rows:
            if STOP.is_set():
                break
            try:
                process_one(db, org, client, item)
            except Exception as exc:
                db.rollback()
                backoff(db, org, item['posting_number'], type(exc).__name__ + ': ' + str(exc)[:120])
                log.warning('OZON_FBS_STICKER_RETRY org=%s posting=%s type=%s',
                            org, item['posting_number'], type(exc).__name__)
            STOP.wait(0.5)
    finally:
        _close_session(db)


def cycle():
    """Legacy manual/test entrypoint; resilient stages, never drop queued work."""
    for kind, fn in (('list', listing_cycle), ('scanit', identifiers_cycle)):
        try:
            fn()
        except Exception:
            log.exception('OZON_FBS_%s_CYCLE_ERROR', kind.upper())
    if PDF_ENABLED:
        try:
            pdf_cycle()
        except Exception:
            log.exception('OZON_FBS_PDF_CYCLE_ERROR')


def _stage_loop(stage, fn, interval):
    while not STOP.is_set():
        started = time.monotonic()
        try:
            fn()
        except Exception:
            log.exception('OZON_FBS_%s_CYCLE_ERROR', stage.upper())
        STOP.wait(max(0.0, interval - (time.monotonic() - started)))


def start():
    global STARTED
    if STARTED or os.getenv('OZON_FBS_STICKERS_ENABLED', 'false').lower() not in ('1', 'true', 'yes'):
        return
    ensure_schema()
    STARTED = True
    STOP.clear()
    workers = [('list', listing_cycle, LIST_INTERVAL),
               ('scanit', identifiers_cycle, SCANIT_INTERVAL)]
    if PDF_ENABLED:
        workers.append(('pdf', pdf_cycle, PDF_INTERVAL))
    for stage, fn, interval in workers:
        threading.Thread(target=_stage_loop, args=(stage, fn, interval),
                         name='ozon-fbs-' + stage, daemon=True).start()
    log.info('OZON_FBS_MONITOR_STARTED list_seconds=%s scanit_seconds=%s '
             'pdf_seconds=%s pdf_actions=%s pdf_enabled=%s',
             LIST_INTERVAL, SCANIT_INTERVAL, PDF_INTERVAL, PDF_ACTIONS, PDF_ENABLED)


def stop():
    STOP.set()
