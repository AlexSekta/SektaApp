"""Read-only preview of marketplace positions after OOS eligibility fix.

Run: python -m backend.scripts.preview_oos_changes --organization-id 2
"""
import argparse
from backend.auth.tenant import tenant_session
from backend.services.out_of_stock_service import _marketplace_identities, calculate_out_of_stock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--organization-id', type=int, required=True)
    args = parser.parse_args()
    with tenant_session(args.organization_id) as db:
        products, positions = _marketplace_identities(db)
        result = calculate_out_of_stock(db)
        for marketplace in ('WB', 'OZON', 'YANDEX'):
            eligible = {product.id for product, _ in positions[marketplace]}
            excluded = [product.seller_article for product in products if product.id not in eligible]
            market = result['marketplaces'][marketplace]
            print(f'{marketplace}: eligible={market["total_products"]} excluded={len(excluded)} oos={market["zero_products"]} percent={market["percent"]}')
            print('  excluded_sample=' + ', '.join(excluded[:25]))
            if marketplace == 'WB':
                print('  HS066_excluded=' + str('HS066' in excluded))
        print('OVERALL:', result['overall'])
        print('READ ONLY: no writes performed')

if __name__ == '__main__':
    main()
