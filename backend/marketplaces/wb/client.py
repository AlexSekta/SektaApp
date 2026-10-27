import os
import requests

from dotenv import load_dotenv

load_dotenv()


WB_API_TOKEN = os.getenv("WB_API_TOKEN")


class WBClient:

    def __init__(self, token: str | None = None):

        token = (token if token is not None else WB_API_TOKEN or "").strip()

        if not token:
            raise RuntimeError("Не указан WB API-токен")

        if token.lower().startswith("bearer "):
            authorization = token
        else:
            authorization = f"Bearer {token}"

        self.token = token
        self.headers = {
            "Authorization": authorization
        }

    # =====================================================
    # СКЛАДЫ WB
    # =====================================================

    def get_warehouses(self):

        url = "https://marketplace-api.wildberries.ru" "/api/v3/warehouses"

        response = requests.get(
            url,
            headers=self.headers,
            timeout=30,
        )

        response.raise_for_status()

        return response.json()

    # =====================================================
    # ТОВАРЫ WB
    # =====================================================

    def get_products(self):

        url = "https://content-api.wildberries.ru" "/content/v2/get/cards/list"

        headers = {
            "Authorization": self.headers["Authorization"],
            "Content-Type": "application/json",
        }

        all_cards = []

        cursor = {"limit": 100}

        while True:

            payload = {
                "settings": {
                    "sort": {"ascending": True},
                    "cursor": cursor,
                    "filter": {"withPhoto": -1},
                }
            }

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()

            data = response.json()

            cards = data.get(
                "cards",
                [],
            )

            cursor_data = data.get(
                "cursor",
                {},
            )

            all_cards.extend(cards)

            if len(cards) < 100:
                break

            if not cursor_data.get("updatedAt"):
                break

            if not cursor_data.get("nmID"):
                break

            cursor = {
                "limit": 100,
                "updatedAt": cursor_data.get("updatedAt"),
                "nmID": cursor_data.get("nmID"),
            }

        return {"cards": all_cards}

    # =====================================================
    # ОТЗЫВЫ WB
    # GET /api/v1/feedbacks
    # =====================================================

    def get_feedbacks(
        self,
        is_answered: bool,
        nm_id: int | None = None,
        take: int = 100,
        skip: int = 0,
        order: str = "dateDesc",
    ):

        url = (
            "https://feedbacks-api.wildberries.ru"
            "/api/v1/feedbacks"
        )

        params = {
            "isAnswered": str(is_answered).lower(),
            "take": max(1, min(int(take), 5000)),
            "skip": max(0, int(skip)),
            "order": order,
        }

        if nm_id is not None:
            params["nmId"] = int(nm_id)

        response = requests.get(
            url,
            headers=self.headers,
            params=params,
            timeout=30,
        )

        if response.status_code == 403:
            detail = None

            try:
                error_data = response.json()
                detail = (
                    error_data.get("detail")
                    or error_data.get("message")
                    or error_data.get("error")
                )
            except ValueError:
                detail = None

            message = (
                "WB API вернул 403 Forbidden для отзывов. "
                "Проверьте, что токен имеет категорию "
                "«Вопросы и отзывы»."
            )

            if detail:
                message += f" Ответ WB: {detail}"

            raise RuntimeError(message)

        response.raise_for_status()
        return response.json()

    # =====================================================
    # ВОПРОСЫ ПОКУПАТЕЛЕЙ
    # =====================================================

    def get_questions(self, is_answered: bool, nm_id: int | None = None, take: int = 100, skip: int = 0, order: str = "dateDesc"):
        url = "https://feedbacks-api.wildberries.ru/api/v1/questions"
        params = {"isAnswered": str(is_answered).lower(), "take": max(1,min(int(take),10000)), "skip": max(0,int(skip)), "order": order}
        if nm_id is not None: params["nmId"] = int(nm_id)
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        if response.status_code == 403: raise RuntimeError("WB API вернул 403 Forbidden для вопросов. Проверьте категорию токена «Вопросы и отзывы».")
        response.raise_for_status(); return response.json()

    def get_unanswered_questions_count(self):
        url = "https://feedbacks-api.wildberries.ru/api/v1/questions/count-unanswered"
        response = requests.get(url, headers=self.headers, timeout=30)
        if response.status_code == 403: raise RuntimeError("WB API вернул 403 Forbidden для счётчика вопросов. Проверьте категорию токена «Вопросы и отзывы».")
        response.raise_for_status(); return response.json()


    # =====================================================
    # FBS ОСТАТКИ WB
    # =====================================================

    def get_stocks(
        self,
        warehouse_id,
        skus,
    ):

        url = "https://marketplace-api.wildberries.ru" f"/api/v3/stocks/{warehouse_id}"

        headers = {
            "Authorization": self.headers["Authorization"],
            "Content-Type": "application/json",
        }

        payload = {"skus": skus}

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()

        return response.json()

    # =====================================================
    # ИЗМЕНЕНИЕ FBS ОСТАТКОВ WB
    # =====================================================

    def update_stocks(
        self,
        warehouse_id,
        stocks,
    ):

        url = "https://marketplace-api.wildberries.ru" f"/api/v3/stocks/{warehouse_id}"

        headers = {
            "Authorization": self.headers["Authorization"],
            "Content-Type": "application/json",
        }

        payload = {"stocks": stocks}

        response = requests.put(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()

        # WB при успешном обновлении может вернуть
        # пустое тело. Не вызываем response.json()
        # без проверки.
        if not response.content:
            return {"status": "ok"}

        try:
            return response.json()

        except ValueError:
            return {
                "status": "ok",
                "raw": response.text,
            }


    # =====================================================
    # ФИНАНСЫ WB — ДЕТАЛИЗАЦИЯ ПРОДАЖ ЗА ПЕРИОД
    # POST /api/finance/v1/sales-reports/detailed
    # =====================================================

    def get_sales_report_detailed_page(
        self,
        date_from: str,
        date_to: str,
        rrd_id: int = 0,
        limit: int = 1000,
        fields: list[str] | None = None,
    ):
        """
        Получает одну страницу детализации отчёта реализации WB.

        Важно: Finance API ограничен 1 запросом в минуту на аккаунт.
        Этот метод намеренно делает только ОДИН HTTP-запрос.
        Пагинация и выдержка лимита будут вынесены в отдельный
        фоновый сборщик после успешного теста.
        """

        url = (
            "https://finance-api.wildberries.ru"
            "/api/finance/v1/sales-reports/detailed"
        )

        payload = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "period": "daily",
            "limit": max(1, min(int(limit), 100000)),
            "rrdId": max(0, int(rrd_id)),
        }

        if fields:
            payload["fields"] = fields

        response = requests.post(
            url,
            headers={
                "Authorization": self.headers["Authorization"],
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )

        if response.status_code == 204:
            return {
                "status_code": 204,
                "rows": [],
                "next_rrd_id": None,
            }

        if response.status_code == 403:
            detail = None
            try:
                error_data = response.json()
                detail = (
                    error_data.get("detail")
                    or error_data.get("message")
                    or error_data.get("error")
                )
            except ValueError:
                pass

            message = (
                "WB API вернул 403 Forbidden для финансового отчёта. "
                "Проверьте, что токен имеет категорию «Финансы» "
                "и является Персональным или Сервисным."
            )
            if detail:
                message += f" Ответ WB: {detail}"
            raise RuntimeError(message)

        response.raise_for_status()

        rows = response.json()
        if not isinstance(rows, list):
            raise RuntimeError(
                "WB Finance API вернул неожиданный формат: ожидался массив строк."
            )

        next_rrd_id = None
        if rows:
            last_rrd_id = rows[-1].get("rrdId")
            if last_rrd_id is not None:
                next_rrd_id = int(last_rrd_id)

        return {
            "status_code": response.status_code,
            "rows": rows,
            "next_rrd_id": next_rrd_id,
        }

    # =====================================================
    # FBO ОСТАТКИ WB — Analytics API
    # =====================================================

    def get_fbw_stocks(
        self,
        nm_ids,
        limit=250000,
    ):
        """
        Получает текущие остатки на складах WB через
        новый Analytics API.

        POST /api/analytics/v1/stocks-report/wb-warehouses

        Метод возвращает остатки на складах WB (FBO),
        одна строка — один размер товара на одном складе.
        """

        url = (
            "https://seller-analytics-api.wildberries.ru"
            "/api/analytics/v1/stocks-report/wb-warehouses"
        )

        headers = {
            "Authorization": self.headers["Authorization"],
            "Content-Type": "application/json",
        }

        nm_ids = [
            int(value)
            for value in nm_ids
            if value is not None
        ]

        if not nm_ids:
            return {
                "data": {
                    "items": []
                }
            }

        import time

        all_items = []

        # WB ограничивает фильтр nmIds максимум 1000 артикулами.
        # Разбиваем большой каталог на пачки.
        batches = [
            nm_ids[index:index + 1000]
            for index in range(0, len(nm_ids), 1000)
        ]

        for batch_index, batch in enumerate(batches):

            offset = 0

            while True:

                payload = {
                    "nmIds": batch,
                    "limit": limit,
                    "offset": offset,
                }

                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=60,
                )

                if response.status_code == 204:
                    break

                response.raise_for_status()

                data = response.json()

                items = (
                    data.get("data", {})
                    .get("items", [])
                )

                all_items.extend(items)

                if len(items) < limit:
                    break

                offset += len(items)

                # Не превышаем лимит WB: 1 запрос / 20 секунд.
                time.sleep(20)

            # Между пачками nmIds также выдерживаем лимит.
            if batch_index < len(batches) - 1:
                time.sleep(20)

        return {
            "data": {
                "items": all_items
            }
        }
