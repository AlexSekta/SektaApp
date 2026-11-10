"""Read remote catalogs and normalize only proven fields. No background synchronization."""
from backend.services.marketplace_clients import (
    get_wb_client, get_ozon_client, get_yandex_client, get_yandex_business_id
)


def clean(v):
    return str(v or '').strip()


def dims(raw):
    if not isinstance(raw, dict):
        return None
    result = {}
    for src, dst in [('length', 'length_cm'), ('width', 'width_cm'), ('height', 'height_cm')]:
        try:
            n = float(raw[src])
            if n <= 0 or n > 10000:
                return None
            result[dst] = n
        except (KeyError, ValueError, TypeError):
            return None
    return result


def normalize_wb(card):
    bars = list(dict.fromkeys(clean(x) for size in (card.get('sizes') or []) for x in (size.get('skus') or []) if clean(x)))
    return {'marketplace':'WB', 'external_id':clean(card.get('nmID')),
            'article':clean(card.get('vendorCode')), 'name':clean(card.get('title')),
            'barcodes':bars, 'dimensions':dims(card.get('dimensions')),
            'platform_ids':{'nmID':clean(card.get('nmID'))}}


def normalize_ozon(card):
    bars = card.get('barcodes') or []
    if not isinstance(bars, list):
        bars = [bars]
    sku = card.get('sku')
    if not sku:
        stocks = (card.get('stocks') or {}).get('stocks') or []
        sku = next((s.get('sku') for s in stocks if s.get('sku')), None)
    dimension_unit = clean(card.get('dimension_unit')).lower()
    package_dimensions = None
    if dimension_unit in ('mm', 'cm'):
        # Ozon calls this field depth; the common catalog calls it length.
        raw = {'length': card.get('depth'), 'width': card.get('width'), 'height': card.get('height')}
        normalized = dims(raw)
        if normalized:
            scale = 0.1 if dimension_unit == 'mm' else 1
            package_dimensions = {k: round(v * scale, 2) for k, v in normalized.items()}
    return {'marketplace':'OZON', 'external_id':clean(card.get('id') or card.get('product_id')),
            'article':clean(card.get('offer_id')), 'name':clean(card.get('name')),
            'barcodes':[clean(x) for x in bars if clean(x)], 'dimensions':package_dimensions,
            'platform_ids':{'product_id':clean(card.get('id') or card.get('product_id')), 'sku':clean(sku)}}


def normalize_yandex(item):
    offer = item.get('offer') or {}
    mapping = item.get('mapping') or {}
    bars = offer.get('barcodes') or []
    wd = offer.get('weightDimensions') or {}
    return {'marketplace':'YANDEX', 'external_id':clean(offer.get('offerId')),
            'article':clean(offer.get('offerId')), 'name':clean(offer.get('name')),
            'barcodes':[clean(b) for b in bars if clean(b)], 'dimensions':dims(wd),
            'platform_ids':{'offerId':clean(offer.get('offerId')), 'marketSku':clean(mapping.get('marketSku'))}}


def read_marketplace(db, marketplace):
    if marketplace == 'WB':
        cards = get_wb_client(db).get_products().get('cards') or []
        data = [normalize_wb(x) for x in cards]
    elif marketplace == 'OZON':
        client = get_ozon_client(db)
        listings = client.get_products().get('items') or []
        data = []
        for idx in range(0, len(listings), 100):
            chunk = listings[idx:idx+100]
            ids = [int(x['product_id']) for x in chunk if x.get('product_id')]
            if not ids:
                continue
            response = client.post('/v3/product/info/list', {'product_id': ids})
            details = response.get('items') or (response.get('result') or {}).get('items') or []
            if not isinstance(details, list):
                raise ValueError('Ozon did not return a valid product list')
            data.extend(normalize_ozon(x) for x in details)
        if listings and not data:
            raise ValueError('Ozon product details missing; import aborted')
    elif marketplace == 'YANDEX':
        client = get_yandex_client(db)
        business = get_yandex_business_id(db, client)
        data = []
        page = None
        seen_tokens = set()
        for _ in range(1000):
            params = {'limit': 100}
            if page:
                params['pageToken'] = page
            response = client.post(f'/v2/businesses/{business}/offer-mappings', {}, params=params)
            result = response.get('result') or {}
            records = result.get('offerMappings') or []
            if not isinstance(records, list):
                raise ValueError('Yandex catalog response malformed')
            data.extend(normalize_yandex(x) for x in records)
            page = (result.get('paging') or {}).get('nextPageToken')
            if not page:
                break
            if page in seen_tokens:
                raise ValueError('Yandex catalog repeated page token')
            seen_tokens.add(page)
        else:
            raise ValueError('Yandex catalog pagination safety limit reached')
    else:
        raise ValueError('Unknown marketplace')
    data = [x for x in data if x['external_id'] and x['article']]
    ids = [x['external_id'] for x in data]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate external IDs from marketplace; import stopped')
    return data
