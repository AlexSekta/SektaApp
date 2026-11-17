"""Pure metadata-only diagnostics for WB Finance detailed report pagination.

Does not contact WB, open a database connection, or alter cursor semantics.
"""


def summarize_page(rows, cursor):
    """Return numeric cursor/order metadata without logging financial rows or tokens."""
    cursor = int(cursor)
    ids = [int(row['rrdId']) for row in rows]
    if not ids:
        return {
            'page_rows': 0, 'page_first': None, 'page_last': None,
            'page_min': None, 'page_max': None, 'ahead': 0,
            'at_or_behind': 0, 'asc_breaks': 0, 'desc_breaks': 0,
            'distinct': 0, 'last_is_max': True,
        }
    return {
        'page_rows': len(ids),
        'page_first': ids[0],
        'page_last': ids[-1],
        'page_min': min(ids),
        'page_max': max(ids),
        'ahead': sum(x > cursor for x in ids),
        'at_or_behind': sum(x <= cursor for x in ids),
        'asc_breaks': sum(b < a for a, b in zip(ids, ids[1:])),
        'desc_breaks': sum(b > a for a, b in zip(ids, ids[1:])),
        'distinct': len(set(ids)),
        'last_is_max': ids[-1] == max(ids),
    }
