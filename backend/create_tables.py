from backend.auth.tenant import ensure_multitenancy_schema

ensure_multitenancy_schema()
print("Таблицы и tenant-схема готовы")
