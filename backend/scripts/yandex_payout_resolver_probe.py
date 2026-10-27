"""Read-only authentication diagnostic for Yandex Market's cabinet payout resolver.

Run from project root:
 python -m backend.scripts.yandex_payout_resolver_probe --org 2

Does not use browser cookies or persist payouts. Only sanitized metadata is printed.
"""
import argparse
import requests
from backend.auth.tenant import tenant_session
from backend.services.marketplace_clients import get_yandex_client

RESOLVER = 'https://partner.market.yandex.ru/api/resolve/?r=dwh/resolveBundleList:resolvePayoutsBundlesList'


def main():
    parser = argparse.ArgumentParser(description='Yandex cabinet payouts: API-key-only diagnostic')
    parser.add_argument('--org', type=int, required=True)
    args = parser.parse_args()
    try:
        with tenant_session(args.org) as db:
            client = get_yandex_client(db)
            api_key = client.headers['Api-Key']
    except Exception as exc:
        print(f'YANDEX_PAYOUT_RESOLVER_CREDENTIALS_ERROR type={type(exc).__name__}')
        return 1

    # This is an internal cabinet endpoint; authorization with Seller API key is not guaranteed.
    # Never follow redirects with the API key and never print the URL/headers/body.
    headers = {'Api-Key': api_key, 'Accept': 'application/json', 'Content-Type': 'application/json'}
    for method in ('GET', 'POST'):
        print(f'YANDEX_PAYOUT_RESOLVER_TEST method={method}')
        try:
            response = requests.request(
                method, RESOLVER, headers=headers,
                json={} if method == 'POST' else None,
                allow_redirects=False, timeout=20,
            )
        except requests.exceptions.RequestException as exc:
            print(f'YANDEX_PAYOUT_RESOLVER_NETWORK_ERROR method={method} type={type(exc).__name__}')
            continue
        try:
            payload = response.json()
            kind = type(payload).__name__
            # Only print high-level shape; do not expose financial data, ids, or internal request details.
            results = payload.get('results') if isinstance(payload, dict) else None
            payout_dates = None
            if isinstance(results, list) and results and isinstance(results[0], dict):
                data = results[0].get('data')
                if isinstance(data, dict) and isinstance(data.get('payoutsByDate'), list):
                    payout_dates = len(data['payoutsByDate'])
            print(f'YANDEX_PAYOUT_RESOLVER_RESULT method={method} status={response.status_code} '
                  f'content_type={response.headers.get("Content-Type", "unknown").split(";")[0]} '
                  f'json_shape={kind} payout_dates={payout_dates if payout_dates is not None else "not_found"}')
        except ValueError:
            print(f'YANDEX_PAYOUT_RESOLVER_RESULT method={method} status={response.status_code} json_shape=non_json')
    print('YANDEX_PAYOUT_RESOLVER_DONE')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
