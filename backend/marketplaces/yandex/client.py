import requests


class YandexAPIError(Exception):
    def __init__(self, status_code: int, message: str, response_data=None):
        self.status_code = status_code
        self.message = message
        self.response_data = response_data
        super().__init__(message)


class YandexClient:
    BASE_URL = "https://api.partner.market.yandex.ru"

    def __init__(self, api_key: str):
        api_key = str(api_key or "").strip()
        if not api_key:
            raise RuntimeError("Не указан API-ключ Яндекс Маркета")

        self.headers = {
            "Api-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _parse_response(self, response):
        try:
            data = response.json()
        except ValueError:
            data = None

        if not response.ok:
            raise YandexAPIError(
                response.status_code,
                self._get_error_message(response.status_code, data),
                data,
            )

        return data if data is not None else {}

    def _request(self, method: str, path: str, params=None, payload=None):
        try:
            response = requests.request(
                method,
                self.BASE_URL + path,
                headers=self.headers,
                params=params,
                json=payload if payload is not None else None,
                timeout=30,
            )
        except requests.Timeout as error:
            raise YandexAPIError(
                504,
                "Яндекс Маркет не ответил вовремя.",
            ) from error
        except requests.ConnectionError as error:
            raise YandexAPIError(
                503,
                "Не удалось подключиться к API Яндекс Маркета.",
            ) from error
        except requests.RequestException as error:
            raise YandexAPIError(
                500,
                "Ошибка соединения с API Яндекс Маркета.",
            ) from error

        return self._parse_response(response)

    def get(self, path: str, params=None):
        return self._request("GET", path, params=params)

    def post(self, path: str, payload=None, params=None):
        return self._request(
            "POST",
            path,
            params=params,
            payload=payload or {},
        )

    def _get_error_message(self, status_code: int, response_data=None):
        api_message = None

        if isinstance(response_data, dict):
            api_message = response_data.get("message") or response_data.get("error")

        if status_code == 400:
            return "Яндекс Маркет отклонил запрос." + (
                f" {api_message}" if api_message else ""
            )
        if status_code == 401:
            return "Ошибка авторизации Яндекс Маркета. Проверьте API-ключ."
        if status_code == 403:
            return "API-ключ Яндекс Маркета не имеет необходимых прав." + (
                f" {api_message}" if api_message else ""
            )
        if status_code == 404:
            return "Ресурс Яндекс Маркета не найден."
        if status_code == 420:
            return "Яндекс Маркет ограничил число параллельных запросов (HTTP 420)." + (
                f" {api_message}" if api_message else ""
            )
        if status_code == 429:
            return "Яндекс Маркет временно ограничил частоту запросов."
        if status_code >= 500:
            return "Ошибка на стороне Яндекс Маркета."
        if api_message:
            return str(api_message)

        return f"Яндекс Маркет вернул ошибку {status_code}."

    def get_campaigns(self):
        return self.get(
            "/v2/campaigns",
            params={"limit": 100},
        )

    # =====================================================
    # ОТЗЫВЫ О ТОВАРАХ
    # POST /v2/businesses/{businessId}/goods-feedback
    # READ ONLY
    # =====================================================

    def get_goods_feedbacks(
        self,
        business_id: int,
        limit: int = 50,
        page_token: str | None = None,
        reaction_status: str = "ALL",
        date_time_from: str | None = None,
        date_time_to: str | None = None,
        feedback_ids: list[int] | None = None,
    ):
        params = {"limit": int(limit)}
        if page_token:
            params["pageToken"] = page_token

        payload = {"reactionStatus": reaction_status}
        if date_time_from:
            payload["dateTimeFrom"] = date_time_from
        if date_time_to:
            payload["dateTimeTo"] = date_time_to
        if feedback_ids:
            payload["feedbackIds"] = [int(value) for value in feedback_ids]

        return self.post(
            f"/v2/businesses/{int(business_id)}/goods-feedback",
            params=params,
            payload=payload,
        )

    # =====================================================
    # ВОПРОСЫ О ТОВАРАХ
    # POST /v1/businesses/{businessId}/goods-questions
    # READ ONLY
    # =====================================================

    def get_goods_feedback_comments(
        self,
        business_id: int,
        feedback_id: int,
        limit: int = 50,
        page_token: str | None = None,
    ):
        params = {"limit": int(limit)}
        if page_token:
            params["pageToken"] = page_token

        return self.post(
            f"/v2/businesses/{int(business_id)}/goods-feedback/comments",
            params=params,
            payload={"feedbackId": int(feedback_id)},
        )

    def get_goods_question_answers(
        self,
        business_id: int,
        question_id: int,
        limit: int = 50,
        page_token: str | None = None,
    ):
        params = {"limit": int(limit)}
        if page_token:
            params["pageToken"] = page_token

        return self.post(
            f"/v1/businesses/{int(business_id)}/goods-questions/answers",
            params=params,
            payload={"questionId": int(question_id)},
        )

    def get_goods_questions(
        self,
        business_id: int,
        limit: int = 50,
        page_token: str | None = None,
        need_answer: bool = False,
        sort: str = "CREATED_AT_DESC",
        date_from: str | None = None,
        date_to: str | None = None,
        question_ids: list[int] | None = None,
    ):
        params = {"limit": int(limit)}

        if page_token:
            params["pageToken"] = page_token

        payload = {
            "needAnswer": bool(need_answer),
            "sort": sort,
        }

        if date_from:
            payload["dateFrom"] = date_from

        if date_to:
            payload["dateTo"] = date_to

        if question_ids:
            payload["questionIds"] = [int(question_id) for question_id in question_ids]

        return self.post(
            f"/v1/businesses/{int(business_id)}/goods-questions",
            params=params,
            payload=payload,
        )

    def get_campaign_stocks(self, campaign_id: int):
        all_warehouses = []
        page_token = None

        while True:
            params = {"limit": 100}

            if page_token:
                params["pageToken"] = page_token

            payload = {
                "withTurnover": False,
                "archived": False,
            }

            data = self.post(
                f"/v2/campaigns/{campaign_id}/offers/stocks",
                payload=payload,
                params=params,
            )

            result = data.get("result", {})
            warehouses = result.get("warehouses", [])
            all_warehouses.extend(warehouses)

            paging = result.get("paging", {})
            next_page_token = paging.get("nextPageToken")

            if not next_page_token or next_page_token == page_token:
                break

            page_token = next_page_token

        return {
            "campaign_id": campaign_id,
            "warehouses": all_warehouses,
            "warehouse_count": len(all_warehouses),
        }

    # =====================================================
    # СКЛАДЫ КАБИНЕТА БЕЗ ГРУПП СКЛАДОВ
    # POST /v3/businesses/{businessId}/warehouses
    # READ ONLY
    # =====================================================

    def get_partner_warehouses(
        self,
        business_id: int,
    ):

        all_warehouses = []
        page_token = None

        while True:

            params = {
                "limit": 30,
            }

            if page_token:

                params["pageToken"] = page_token

            data = self.post(
                (f"/v3/businesses/" f"{business_id}/warehouses"),
                payload={},
                params=params,
            )

            result = data.get(
                "result",
                {},
            )

            warehouses = result.get(
                "warehouses",
                [],
            )

            all_warehouses.extend(warehouses)

            paging = result.get(
                "paging",
                {},
            )

            next_page_token = paging.get("nextPageToken")

            if not next_page_token:

                break

            if next_page_token == page_token:

                break

            page_token = next_page_token

        return {
            "business_id": business_id,
            "warehouses": all_warehouses,
            "warehouse_count": len(all_warehouses),
        }

    # =====================================================
    # СКЛАДЫ / ГРУППЫ СКЛАДОВ
    # POST /v2/businesses/{businessId}/warehouses
    # READ ONLY
    #
    # Используем для диагностики наличия групп складов.
    # =====================================================

    def get_grouped_warehouses(
        self,
        business_id: int,
        campaign_ids: list[int] | None = None,
    ):

        all_warehouses = []
        page_token = None

        while True:

            params = {
                "limit": 30,
            }

            if page_token:

                params["pageToken"] = page_token

            payload = {}

            if campaign_ids:

                payload["campaignIds"] = campaign_ids

            data = self.post(
                (f"/v2/businesses/" f"{business_id}/warehouses"),
                payload=payload,
                params=params,
            )

            result = data.get(
                "result",
                {},
            )

            warehouses = result.get(
                "warehouses",
                [],
            )

            all_warehouses.extend(warehouses)

            paging = result.get(
                "paging",
                {},
            )

            next_page_token = paging.get("nextPageToken")

            if not next_page_token:

                break

            if next_page_token == page_token:

                break

            page_token = next_page_token

        return {
            "business_id": business_id,
            "warehouses": all_warehouses,
            "warehouse_count": len(all_warehouses),
        }

    # =====================================================
    # ПОЛУЧЕНИЕ FBS-ОСТАТКОВ КАБИНЕТА
    # POST /v3/businesses/{businessId}/offers/stocks
    #
    # Для кабинетов без групп складов.
    # Возвращает остатки конкретного склада партнёра.
    # =====================================================

    def get_partner_stocks(
        self,
        business_id: int,
        partner_warehouse_id: int,
        offer_ids: list[str] | None = None,
    ):
        """
        Получить остатки FBS на складе партнёра.

        Если переданы offer_ids, Яндекс возвращает только
        эти SKU. Это предпочтительно для точечной проверки
        одного товара после изменения остатка.

        Без offer_ids выполняется постраничная загрузка
        всех товаров склада.
        """

        if offer_ids:
            cleaned_offer_ids = [
                str(offer_id).strip()
                for offer_id in offer_ids
                if str(offer_id).strip()
            ]

            if not cleaned_offer_ids:
                return {
                    "business_id": business_id,
                    "partnerWarehouseId": partner_warehouse_id,
                    "offers": [],
                }

            data = self.post(
                f"/v3/businesses/{business_id}/offers/stocks",
                payload={
                    "partnerWarehouseId": int(partner_warehouse_id),
                    "offerIds": cleaned_offer_ids,
                },
            )

            result = data.get("result", {})

            return {
                "business_id": business_id,
                "partnerWarehouseId": int(
                    result.get(
                        "partnerWarehouseId",
                        partner_warehouse_id,
                    )
                ),
                "offers": result.get("offers", []),
                "paging": result.get("paging", {}),
            }

        all_offers = []
        page_token = None

        while True:
            params = {
                "limit": 100,
            }

            if page_token:
                params["pageToken"] = page_token

            data = self.post(
                f"/v3/businesses/{business_id}/offers/stocks",
                params=params,
                payload={
                    "partnerWarehouseId": int(partner_warehouse_id),
                    "archived": False,
                },
            )

            result = data.get("result", {})

            all_offers.extend(
                result.get("offers", [])
            )

            paging = result.get("paging", {})
            next_page_token = paging.get("nextPageToken")

            if not next_page_token or next_page_token == page_token:
                break

            page_token = next_page_token

        return {
            "business_id": business_id,
            "partnerWarehouseId": int(partner_warehouse_id),
            "offers": all_offers,
            "warehouse_count": 1,
        }

    # =====================================================
    # ПОЛУЧЕНИЕ AVAILABLE ОДНОГО FBS-ТОВАРА
    # POST /v3/businesses/{businessId}/offers/stocks
    # =====================================================

    def get_confirmed_partner_stock(
        self,
        business_id: int,
        partner_warehouse_id: int,
        offer_id: str,
    ):
        response = self.get_partner_stocks(
            business_id=business_id,
            partner_warehouse_id=partner_warehouse_id,
            offer_ids=[offer_id],
        )

        for offer in response.get("offers", []):
            if str(offer.get("offerId")) != str(offer_id):
                continue

            available_stock = 0

            for stock_item in offer.get("stocks", []):
                if stock_item.get("type") == "AVAILABLE":
                    available_stock = int(
                        stock_item.get("count", 0)
                    )
                    break

            return {
                "offer_id": str(offer_id),
                "warehouse_id": int(partner_warehouse_id),
                "available": available_stock,
                "updated_at": offer.get("updatedAt"),
                "raw": offer,
            }

        return None

    # =====================================================
    # ИЗМЕНЕНИЕ FBS-ОСТАТКОВ
    # ВНИМАНИЕ:
    # Метод подготовлен, но пока НЕ вызывается из /stocks/update.
    # =====================================================

    def update_partner_stocks(
        self,
        business_id: int,
        stocks: list,
    ):

        if not stocks:

            raise ValueError("Не переданы остатки для обновления")

        sku_items = []

        for item in stocks:

            sku = item.get("sku")

            warehouse_id = item.get("partnerWarehouseId")

            count = item.get("count")

            if not sku:

                raise ValueError("Не указан SKU товара")

            if warehouse_id is None:

                raise ValueError("Не указан partnerWarehouseId")

            if count is None:

                raise ValueError("Не указан остаток")

            count = int(count)

            if count < 0:

                raise ValueError("Остаток не может быть отрицательным")

            sku_items.append(
                {
                    "sku": str(sku),
                    "partnerWarehouseId": int(warehouse_id),
                    "count": count,
                }
            )

        return self.post(
            (f"/v3/businesses/" f"{business_id}/" f"offers/stocks/update"),
            payload={
                "skuItems": sku_items,
            },
        )

    # =====================================================
    # ПРОВЕРКА ОСТАТКА ОДНОГО ТОВАРА
    #
    # Оставляем старое имя метода для совместимости
    # с существующим stock_service.py, но внутри уже
    # используем актуальный v3 business-level API.
    # =====================================================

    def get_confirmed_campaign_stock(
        self,
        campaign_id: int,
        warehouse_id: int,
        offer_id: str,
        business_id: int | None = None,
    ):
        """
        Совместимый wrapper.

        campaign_id здесь больше не используется для чтения:
        для кабинета без групп складов проверяем остаток
        через businessId + partnerWarehouseId.

        businessId берём из текущей конфигурации проекта.
        """

        if business_id is None:
            raise ValueError("Не указан business_id для проверки остатка Yandex")

        return self.get_confirmed_partner_stock(
            business_id=business_id,
            partner_warehouse_id=warehouse_id,
            offer_id=offer_id,
        )
