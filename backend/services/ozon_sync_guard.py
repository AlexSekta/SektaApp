"""One in-process lock for order/event collectors; avoids concurrent DB rewrites and Ozon rate bursts."""
import threading
sync_guard = threading.Lock()
