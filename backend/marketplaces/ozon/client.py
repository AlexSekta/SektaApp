import requests


# =========================================================
# ОШИБКА OZON API
# =========================================================


class OzonAPIError(Exception):

    def __init__(
        self,
        status_code: int,
        message: str,
        response_data=None,
    ):

        self.status_code = status_code
        self.message = message
        self.response_data = response_data

        super().__init__(message)


# =========================================================
# OZON CLIENT
# =========================================================


class OzonClient:

    BASE_URL = "https://api-seller.ozon.ru"

    def __init__(self, client_id: str, api_key: str):

        client_id = str(client_id or "").strip()
        api_key = str(api_key or "").strip()

        if not client_id:
            raise RuntimeError("Не указан Client ID Ozon")

        if not api_key:
            raise RuntimeError("Не указан API-ключ Ozon")

        self.client_id = client_id
        self.api_key = api_key
        self.headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # =====================================================
    # ДИАГНОСТИЧЕСКИЙ POST
    # =====================================================

    def post_raw(
        self,
        path: str,
        payload: dict | None = None,
    ):
        """
        Выполняет POST к Ozon и возвращает исходный HTTP-код и тело.
        Нужен для диагностических endpoint'ов, чтобы не скрывать
        реальную ошибку Ozon за OzonAPIError.
        """
        url = self.BASE_URL + path

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=payload or {},
                timeout=30,
            )
        except requests.Timeout as error:
            return {
                "status_code": 504,
                "body": {"error": "timeout", "message": str(error)},
            }
        except requests.ConnectionError as error:
            return {
                "status_code": 503,
                "body": {"error": "connection", "message": str(error)},
            }
        except requests.RequestException as error:
            return {
                "status_code": 500,
                "body": {"error": "request", "message": str(error)},
            }

        try:
            body = response.json()
        except ValueError:
            body = response.text

        return {
            "status_code": response.status_code,
            "body": body,
        }

    # =====================================================
    # БАЗОВЫЙ POST
    # =====================================================

    def post(
        self,
        path: str,
        payload: dict | None = None,
    ):

        url = self.BASE_URL + path

        try:

            response = requests.post(
                url,
                headers=self.headers,
                json=payload or {},
                timeout=30,
            )

        except requests.Timeout as error:

            raise OzonAPIError(
                status_code=504,
                message=("Ozon не ответил вовремя. " "Повторите попытку."),
            ) from error

        except requests.ConnectionError as error:

            raise OzonAPIError(
                status_code=503,
                message=("Не удалось подключиться " "к Ozon API."),
            ) from error

        except requests.RequestException as error:

            raise OzonAPIError(
                status_code=500,
                message=("Ошибка соединения с Ozon API."),
            ) from error

        # =================================================
        # ЧИТАЕМ ОТВЕТ
        # =================================================

        try:

            response_data = response.json()

        except ValueError:

            response_data = None

        # =================================================
        # HTTP ОШИБКА
        # =================================================

        if not response.ok:

            status_code = response.status_code

            message = self._get_error_message(
                status_code=status_code,
                response_data=response_data,
            )

            raise OzonAPIError(
                status_code=status_code,
                message=message,
                response_data=response_data,
            )

        # =================================================
        # УСПЕХ
        # =================================================

        if response_data is None:

            return {}

        return response_data

    # =====================================================
    # ПОНЯТНЫЕ СООБЩЕНИЯ ОБ ОШИБКАХ
    # =====================================================

    def _get_error_message(
        self,
        status_code: int,
        response_data,
    ):

        if status_code == 400:

            return "Ozon отклонил запрос. " "Проверьте переданные данные."

        if status_code == 401:

            return "Ошибка авторизации Ozon. " "Проверьте Client ID и API-ключ."

        if status_code == 403:

            # Ozon может вернуть конкретную причину отказа
            if isinstance(response_data, dict):
                ozon_message = response_data.get("message")

                if ozon_message:
                    return f"Ozon отказал в доступе: {ozon_message}"

            return (
                "Ozon отказал в доступе к этой операции. "
                "Проверьте права API-ключа и наличие необходимого доступа "
                "к Review API."
            )

        if status_code == 404:

            return "Запрашиваемый ресурс " "Ozon не найден."

        if status_code == 429:

            return (
                "Ozon временно ограничил "
                "частоту запросов. "
                "Повторите попытку позже."
            )

        if status_code >= 500:

            return "На стороне Ozon произошла ошибка. " "Повторите попытку позже."

        # Пытаемся использовать сообщение Ozon
        if isinstance(
            response_data,
            dict,
        ):

            ozon_message = response_data.get("message")

            if ozon_message:

                return str(ozon_message)

        return f"Ozon API вернул ошибку " f"{status_code}."

    # =====================================================
    # ИНФОРМАЦИЯ О ПРОДАВЦЕ
    # =====================================================

    def get_seller_info(self):

        return self.post(
            "/v1/seller/info",
            {},
        )

    # =====================================================
    # КАТАЛОГ ТОВАРОВ
    # =====================================================

    def get_products(self):

        all_products = []

        last_id = ""

        while True:

            payload = {
                "filter": {
                    "visibility": "ALL",
                },
                "last_id": last_id,
                "limit": 1000,
            }

            data = self.post(
                "/v3/product/list",
                payload,
            )

            result = data.get(
                "result",
                {},
            )

            items = result.get(
                "items",
                [],
            )

            all_products.extend(items)

            new_last_id = result.get(
                "last_id",
                "",
            )

            if not items:
                break

            if len(items) < 1000:
                break

            if not new_last_id or new_last_id == last_id:
                break

            last_id = new_last_id

        return {
            "items": all_products,
        }

    # =====================================================
    # АНАЛИТИКА
    # POST /v1/analytics/data
    # =====================================================

    def get_analytics_data(
        self,
        date_from: str,
        date_to: str,
        metrics: list[str],
        dimensions: list[str],
        filters: list[dict] | None = None,
        sort: list[dict] | None = None,
        limit: int = 1000,
        offset: int = 0,
    ):
        payload = {
            "date_from": str(date_from),
            "date_to": str(date_to),
            "metrics": list(metrics),
            "dimension": list(dimensions),
            "filters": list(filters or []),
            "sort": list(sort or []),
            "limit": max(1, min(int(limit), 1000)),
            "offset": max(0, int(offset)),
        }
        return self.post("/v1/analytics/data", payload)

    # =====================================================
    # ПОЗАКАЗНЫЕ ОТПРАВЛЕНИЯ FBO / FBS — СЫРОЙ API
    # =====================================================

    def list_fbo_postings_raw(
        self,
        since: str,
        to: str,
        cursor: str = "",
        limit: int = 1000,
    ):
        return self.post_raw(
            "/v3/posting/fbo/list",
            {
                "cursor": str(cursor or ""),
                "filter": {"since": str(since), "to": str(to)},
                "limit": max(1, min(int(limit), 1000)),
                "sort_dir": "asc",
                "with": {
                    "analytics_data": False,
                    "financial_data": True,
                    "legal_info": False,
                },
            },
        )

    def list_fbs_postings_raw(
        self,
        since: str,
        to: str,
        cursor: str = "",
        limit: int = 1000,
    ):
        return self.post_raw(
            "/v4/posting/fbs/list",
            {
                "cursor": str(cursor or ""),
                "filter": {"since": str(since), "to": str(to)},
                "limit": max(1, min(int(limit), 1000)),
                "sort_dir": "asc",
                "with": {
                    "analytics_data": False,
                    "barcodes": False,
                    "financial_data": True,
                    "legal_info": False,
                    "translit": False,
                },
            },
        )

    # =====================================================
    # ОБЩИЕ ОСТАТКИ
    # FBO / FBS / RFBS
    # =====================================================

    def get_stocks(self):

        all_items = []

        cursor = ""

        while True:

            payload = {
                "cursor": cursor,
                "filter": {
                    "visibility": "ALL",
                },
                "limit": 1000,
            }

            data = self.post(
                "/v4/product/info/stocks",
                payload,
            )

            items = data.get(
                "items",
                [],
            )

            all_items.extend(items)

            new_cursor = data.get(
                "cursor",
                "",
            )

            if not items:
                break

            if len(items) < 1000:
                break

            if not new_cursor or new_cursor == cursor:
                break

            cursor = new_cursor

        return {
            "items": all_items,
        }

    # =====================================================
    # FBS ПО СКЛАДАМ
    # =====================================================

    def get_fbs_stocks(self):

        products_data = self.get_products()

        products = products_data.get(
            "items",
            [],
        )

        offer_ids = [
            product.get("offer_id") for product in products if product.get("offer_id")
        ]

        if not offer_ids:

            return {
                "products": [],
                "count": 0,
            }

        all_products = []

        cursor = ""

        while True:

            payload = {
                "offer_id": offer_ids,
                "limit": 1000,
            }

            if cursor:

                payload["cursor"] = cursor

            data = self.post(
                "/v2/product/info/stocks-by-warehouse/fbs",
                payload,
            )

            products_page = data.get(
                "products",
                [],
            )

            all_products.extend(products_page)

            has_next = data.get(
                "has_next",
                False,
            )

            new_cursor = data.get(
                "cursor",
                "",
            )

            if not has_next:
                break

            if not new_cursor:
                break

            if new_cursor == cursor:
                break

            cursor = new_cursor

        return {
            "products": all_products,
            "count": len(all_products),
        }

    # =====================================================
    # FBO ПО СКЛАДАМ
    # =====================================================

    def get_fbo_stocks(self):

        payload = {
            "limit": 1000,
            "offset": 0,
            "warehouse_type": "ALL",
        }

        return self.post(
            "/v2/analytics/stock_on_warehouses",
            payload,
        )

    # =====================================================
    # ИЗМЕНЕНИЕ FBS ОСТАТКОВ
    # =====================================================

    def update_stocks(
        self,
        stocks: list,
    ):

        if not stocks:

            raise ValueError("Не переданы остатки " "для обновления")

        if len(stocks) > 100:

            raise ValueError("За один запрос можно " "передать максимум 100 товаров")

        payload = {"stocks": stocks}

        return self.post(
            "/v2/products/stocks",
            payload,
        )

    # =====================================================
    # ОТЗЫВЫ OZON — V1
    # Ozon API: POST /v1/review/count
    #          POST /v1/review/list
    #          POST /v1/review/info
    # =====================================================

    def get_review_count_v1(self):
        return self.post(
            "/v1/review/count",
            {},
        )

    # Совместимость со старым /ozon/reviews endpoint.
    def get_review_count(self):
        return self.get_review_count_v1()

    def get_reviews_v1(
        self,
        status=None,
        limit=100,
        last_id="",
        sort_dir="DESC",
    ):
        payload = {
            "limit": max(1, min(int(limit), 100)),
            "sort_dir": sort_dir,
        }

        if last_id:
            payload["last_id"] = last_id

        if status:
            payload["status"] = status

        return self.post(
            "/v1/review/list",
            payload,
        )

    def get_review_info_v1(
        self,
        review_id,
    ):
        return self.post(
            "/v1/review/info",
            {
                "review_id": str(review_id),
            },
        )

    def get_review_product_info(
        self,
        skus,
    ):
        cleaned = [str(sku).strip() for sku in skus if str(sku).strip()]

        if not cleaned:
            return {"items": []}

        return self.post(
            "/v3/product/info/list",
            {
                "sku": cleaned[:1000],
            },
        )

    # =====================================================
    # СКЛАДЫ
    # =====================================================

    def get_warehouses(self):

        return self.post(
            "/v2/warehouse/list",
            {},
        )
