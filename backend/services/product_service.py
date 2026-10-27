from datetime import datetime

from sqlalchemy.orm import Session

from backend.models.product import Product



def save_products(
    db: Session,
    cards
):

    saved = 0


    for card in cards:


        sizes = card.get(
            "sizes",
            []
        )


        barcode = None

        chrt_id = None



        if sizes:


            chrt_id = sizes[0].get(
                "chrtID"
            )


            skus = sizes[0].get(
                "skus",
                []
            )


            if skus:

                barcode = skus[0]




        seller_article = card.get(
            "vendorCode"
        )


        if not seller_article:

            continue





        product = db.query(
            Product
        ).filter(

            Product.seller_article ==
            seller_article

        ).first()





        if product:


            product.marketplace = "WB"


            product.nm_id = str(
                card["nmID"]
            )


            product.barcode = barcode


            product.chrt_id = (

                str(chrt_id)

                if chrt_id

                else None

            )


            product.name = card.get(
                "title"
            )


            product.updated_at = datetime.utcnow()



        else:


            product = Product(

                marketplace="WB",

                nm_id=str(
                    card["nmID"]
                ),

                seller_article=
                    seller_article,

                barcode=barcode,

                chrt_id=(

                    str(chrt_id)

                    if chrt_id

                    else None

                ),

                name=
                    card.get("title"),

                updated_at=datetime.utcnow()

            )


            db.add(product)




        saved += 1



    db.commit()



    return saved