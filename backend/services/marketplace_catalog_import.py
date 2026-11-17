"""Read remote catalogs and normalize only proven fields. No background synchronization."""
import logging

from backend.services.marketplace_clients import (
    get_wb_client, get_ozon_client, get_yandex_client, get_yandex_business_id
)


logger = logging.getLogger(__name__)


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


def ozon_package_dimensions(card):
    """Use the units returned by Ozon; never infer millimetres from a number."""
    raw_unit = clean(card.get('dimension_unit')).lower()
    if raw_unit not in ('mm', 'cm', 'in'):
        return None, ('INVALID_UNIT' if raw_unit else 'MISSING_UNIT')
    raw = {'length':card.get('depth'), 'width':card.get('width'), 'height':card.get('height')}
    numbers = dims(raw)
    if not numbers:
        return None, 'MISSING_VALUES'
    factor = {'mm':0.1,'cm':1.0,'in':2.54}[raw_unit]
    result = {key:round(value * factor, 2) for key,value in numbers.items()}
    if any(value <= 0 or value > 1000 for value in result.values()):
        return None, 'INVALID_VALUES'
    return result, 'OK'


def normalize_ozon(card):
    bars = card.get('barcodes') or []
    if not isinstance(bars, list):
        bars = [bars]
    sku = card.get('sku')
    if not sku:
        stocks = (card.get('stocks') or {}).get('stocks') or []
        sku = next((s.get('sku') for s in stocks if s.get('sku')), None)
    package_dimensions, state = ozon_package_dimensions(card)
    return {'marketplace':'OZON', 'external_id':clean(card.get('id') or card.get('product_id')),
            'article':clean(card.get('offer_id')), 'name':clean(card.get('name')),
            'barcodes':[clean(x) for x in bars if clean(x)], 'dimensions':package_dimensions,
            'dimension_fetch_status':state,
            'dimension_source':'v3/product/info/list' if package_dimensions else None,
            'dimension_native':{'values':[card.get('depth'),card.get('width'),card.get('height')],
                                'unit':clean(card.get('dimension_unit')).lower()} if package_dimensions else None,
            'platform_ids':{'product_id':clean(card.get('id') or card.get('product_id')), 'sku':clean(sku)}}


def enrich_ozon_dimensions(client, normalized_rows):
    """Fetch missing dimensions from attributes without overwriting v3's valid data.

    Failures are explicit on each affected row: an API error is not evidence
    that dimensions are absent on the marketplace.
    """
    missing = [r for r in normalized_rows if r['dimensions'] is None]
    for start in range(0, len(missing), 100):
        chunk = missing[start:start + 100]
        by_id = {r['external_id']:r for r in chunk}
        product_ids = [int(k) for k in by_id]
        try:
            response = client.post('/v4/product/info/attributes', {
                'filter':{'product_id':product_ids}, 'limit':len(product_ids)})
            attributes = response.get('result')
            if not isinstance(attributes, list):
                raise ValueError('Unexpected Ozon attributes response: result is not a list')
            received_ids = set()
            for card in attributes:
                if not isinstance(card, dict):
                    continue
                key = clean(card.get('id') or card.get('product_id'))
                row = by_id.get(key)
                if not row:
                    continue
                received_ids.add(key)
                values, state = ozon_package_dimensions(card)
                if values:
                    row['dimensions'] = values
                    row['dimension_fetch_status'] = 'OK'
                    row['dimension_source'] = 'v4/product/info/attributes'
                    row['dimension_native'] = {'values':[card.get('depth'),card.get('width'),card.get('height')],
                                               'unit':clean(card.get('dimension_unit')).lower()}
                else:
                    row['dimension_fetch_status'] = state
                    row['dimension_source'] = 'v4/product/info/attributes'
            for key, row in by_id.items():
                if key not in received_ids:
                    row['dimension_fetch_status'] = 'NOT_RETURNED'
        except Exception:
            logger.exception('OZON_DIMENSION_ATTRIBUTES_FAILED count=%s',len(chunk))
            for row in chunk:
                row['dimension_fetch_status'] = 'API_ERROR'
                row['dimension_source'] = None



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
            normalized = [normalize_ozon(x) for x in details]
            enrich_ozon_dimensions(client, normalized)
            data.extend(normalized)
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
