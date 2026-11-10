"""One-time targeted WB catalog repair: dry-run unless --apply.
Usage: python -m backend.scripts.repair_wb_catalog --organization-id 2
       python -m backend.scripts.repair_wb_catalog --organization-id 2 --apply
Never changes master_products, stock_history, or other marketplaces.
"""
import argparse
from backend.auth.tenant import tenant_session
from backend.models.product import Product
from backend.services.marketplace_clients import get_wb_client
from backend.services.product_service import save_products

EXPECTED = {
    "HS218": "1840650707",
    "HS225": "1970402141",
    "HS226": "1970294237",
    "HS227": "1970294238",
    "HS219": "151451408",
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.organization_id < 1:
        parser.error("organization-id must be positive")
    with tenant_session(args.organization_id) as db:
        cards = get_wb_client(db).get_products().get("cards") or []
        found = {}
        for card in cards:
            article = str(card.get("vendorCode") or "").strip()
            nm = str(card.get("nmID") or "").strip()
            if article in EXPECTED:
                if article in found or EXPECTED[article] != nm:
                    raise RuntimeError(f"WB card identity mismatch: {article} / nmID={nm}")
                found[article] = card
        missing = set(EXPECTED) - set(found)
        if missing:
            raise RuntimeError(f"WB API missing expected cards: {sorted(missing)}")
        changes = []
        for article, nm in EXPECTED.items():
            matches = db.query(Product).filter(Product.marketplace == "WB", Product.nm_id == nm).all()
            if len(matches) > 1:
                raise RuntimeError(f"Duplicate local WB nmID={nm}")
            collision = db.query(Product).filter(Product.marketplace == "WB", Product.seller_article == article).all()
            if any(p.nm_id != nm for p in collision):
                raise RuntimeError(f"Conflicting WB article: {article}")
            action = ("ADD" if not matches else "RENAME" if matches[0].seller_article != article else "PRESENT")
            changes.append((article, nm, action))
            print(f"{action:7} {article:6} nmID={nm}")
        if not args.apply:
            print("DRY RUN: database unchanged. Re-run with --apply after backup.")
            return
        to_save = [found[article] for article, nm, action in changes if action != "PRESENT"]
        if to_save:
            save_products(db, to_save)
        print(f"APPLIED: {len(to_save)} WB products updated/inserted; no stocks rewritten.")

if __name__ == "__main__":
    main()
