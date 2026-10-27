from datetime import datetime

from sqlalchemy.orm import Session

from backend.models.warehouse import Warehouse


def save_warehouses(
    db: Session,
    warehouses
):

    for item in warehouses:

        existing = db.query(
            Warehouse
        ).filter(
            Warehouse.warehouse_id == str(item["id"]),
            Warehouse.marketplace == "WB"
        ).first()


        if existing:

            existing.warehouse_name = item["name"]
            existing.updated_at = datetime.utcnow()

        else:

            warehouse = Warehouse(

                marketplace="WB",

                warehouse_id=str(
                    item["id"]
                ),

                warehouse_name=item["name"],

                warehouse_type="SELLER"
            )

            db.add(warehouse)


    db.commit()


    return len(warehouses)