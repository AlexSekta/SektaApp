r"""Generate and download a Yandex Market payment report, without database writes.

Run from the project root:
  .\venv\Scripts\python.exe -m backend.scripts.yandex_payout_probe --org 2 --from 2026-10-01 --to 2026-10-31

The report is generated in the official Yandex API and downloaded to a local file.
Do not share the generated archive publicly: it contains business financial records.
"""
import argparse
from datetime import date
from pathlib import Path
import time
import zipfile
from io import BytesIO
from urllib.parse import urlparse

import requests
from backend.database import SessionLocal
from backend.auth.tenant import set_app_db_role, set_tenant_context, clear_tenant_context, reset_app_db_role
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.marketplaces.yandex.client import YandexAPIError


def main():
    parser = argparse.ArgumentParser(description="Read-only Yandex payment report diagnostic")
    parser.add_argument('--org', type=int, required=True, help='Organization ID')
    parser.add_argument('--from', dest='start', type=date.fromisoformat, required=True)
    parser.add_argument('--to', dest='end', type=date.fromisoformat, required=True)
    parser.add_argument('--out', default='yandex_payment_diagnostic', help='Local output folder')
    args = parser.parse_args()
    if args.start > args.end or (args.end - args.start).days > 90:
        parser.error('Choose a period of up to 91 days')

    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, args.org)
        client = get_yandex_client(db)
        business_id = get_yandex_business_id(db, client)
        # Credentials are used only in requests; never printed or saved to report files.
        print(f'YANDEX_PAYOUT_GENERATE org={args.org} from={args.start} to={args.end}', flush=True)
        response = client.post('/v2/reports/united-netting/generate',
                               payload={'businessId': business_id,
                                        'dateFrom': args.start.isoformat(),
                                        'dateTo': args.end.isoformat()},
                               params={'format': 'JSON', 'language': 'RU'})
        report_id = (response.get('result') or {}).get('reportId')
        if not report_id:
            print('YANDEX_PAYOUT_UNEXPECTED_GENERATE_RESPONSE keys=', list(response), flush=True)
            return 2
        print('YANDEX_PAYOUT_REPORT_CREATED', flush=True)
        for attempt in range(15):
            status_response = client.get(f'/v2/reports/info/{report_id}')
            result = status_response.get('result') or {}
            status = str(result.get('status') or '')
            print(f'YANDEX_PAYOUT_STATUS {status or "UNKNOWN"}', flush=True)
            if status == 'DONE':
                url = result.get('file')
                if not url:
                    print('YANDEX_PAYOUT_ERROR: file link missing')
                    return 3
                parsed = urlparse(url)
                if parsed.scheme != 'https' or not (parsed.hostname == 'yandex.ru' or parsed.hostname.endswith('.yandex.ru') or parsed.hostname == 'yandex.net' or parsed.hostname.endswith('.yandex.net') or parsed.hostname == 'yandexcloud.net' or parsed.hostname.endswith('.yandexcloud.net')):
                    print('YANDEX_PAYOUT_ERROR: unexpected report download host')
                    return 4
                content = None
                for download_attempt in range(1, 5):
                    try:
                        download = requests.get(url, timeout=(15, 120), allow_redirects=False)
                        download.raise_for_status()
                        if len(download.content) > 40_000_000:
                            print('YANDEX_PAYOUT_ERROR: report too large')
                            return 5
                        if not zipfile.is_zipfile(BytesIO(download.content)):
                            print('YANDEX_PAYOUT_ERROR: downloaded file is not a ZIP archive')
                            return 9
                        content = download.content
                        break
                    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                            requests.exceptions.Timeout) as exc:
                        # Do not print exc: requests exceptions include the signed report URL.
                        print(f'YANDEX_PAYOUT_DOWNLOAD_RETRY attempt={download_attempt}/4 type={type(exc).__name__}', flush=True)
                        if download_attempt == 4:
                            print('YANDEX_PAYOUT_DOWNLOAD_FAILED: network or SSL error; signed URL omitted', flush=True)
                            return 10
                        time.sleep(3 * download_attempt)
                    except requests.exceptions.HTTPError as exc:
                        status_code = exc.response.status_code if exc.response is not None else 'unknown'
                        print(f'YANDEX_PAYOUT_DOWNLOAD_HTTP_ERROR status={status_code}; signed URL omitted', flush=True)
                        return 11
                if content is None:
                    return 10
                out_dir = Path(args.out)
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f'yandex_payments_{args.start}_{args.end}.zip'
                out_file.write_bytes(content)
                print(f'YANDEX_PAYOUT_SAVED {out_file} size={len(content)} bytes')
                print('NOTE: File includes financial details. Do not share it without reviewing/redacting sensitive fields.')
                return 0
            if status in ('FAILED', 'NO_DATA'):
                print(f'YANDEX_PAYOUT_STOP status={status}')
                return 6
            if attempt < 14:
                time.sleep(20)
        print('YANDEX_PAYOUT_PENDING: report is still being generated. Repeat later with report ID saved privately; do not generate multiple identical reports.')
        return 7
    except YandexAPIError as exc:
        print(f'YANDEX_PAYOUT_API_ERROR status={exc.status_code} message={exc.message}')
        return 8
    finally:
        try:
            clear_tenant_context(db)
            reset_app_db_role(db)
        finally:
            db.close()


if __name__ == '__main__':
    raise SystemExit(main())
