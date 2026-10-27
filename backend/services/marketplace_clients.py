from backend.marketplaces.wb.client import WBClient
from backend.marketplaces.ozon.client import OzonClient
from backend.marketplaces.yandex.client import YandexClient, YandexAPIError
from backend.services.marketplace_credentials import (
    MarketplaceNotConfiguredError,
    get_marketplace_credentials,
)


def get_wb_client(db):
    credentials = get_marketplace_credentials(db, "WB")
    token = str(credentials.get("token") or "").strip()

    if not token:
        raise MarketplaceNotConfiguredError(
            "WB: сохранённый API-ключ пустой."
        )

    return WBClient(token=token)



def get_ozon_client(db):
    credentials = get_marketplace_credentials(db, "OZON")
    client_id = str(credentials.get("client_id") or "").strip()
    api_key = str(credentials.get("api_key") or "").strip()

    if not client_id or not api_key:
        raise MarketplaceNotConfiguredError(
            "OZON: сохранённые Client ID или API-ключ пусты."
        )

    return OzonClient(client_id=client_id, api_key=api_key)


def get_yandex_client(db):
    credentials = get_marketplace_credentials(db, "YANDEX")
    api_key = str(credentials.get("api_key") or "").strip()

    if not api_key:
        raise MarketplaceNotConfiguredError(
            "YANDEX: сохранённый API-ключ пустой."
        )

    return YandexClient(api_key=api_key)


def get_yandex_business_id(db, client=None) -> int:
    credentials = get_marketplace_credentials(db, "YANDEX")
    configured = credentials.get("business_id")
    if configured not in (None, ""):
        try:
            value = int(configured)
        except (TypeError, ValueError) as exc:
            raise MarketplaceNotConfiguredError(
                "YANDEX: сохранённый Business ID имеет неверный формат."
            ) from exc
        if value < 1:
            raise MarketplaceNotConfiguredError(
                "YANDEX: сохранённый Business ID должен быть положительным."
            )
        return value

    client = client or get_yandex_client(db)
    campaigns = client.get_campaigns().get("campaigns", []) or []
    if not campaigns:
        raise YandexAPIError(404, "Не найден ни один кабинет Яндекс Маркета.")

    value = (campaigns[0].get("business") or {}).get("id")
    if value is None:
        raise YandexAPIError(500, "Яндекс Маркет не вернул businessId кабинета.")
    return int(value)
