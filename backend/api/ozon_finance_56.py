"""Read-only tenant-scoped Ozon accruals. No official payment status implied."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.auth.security import require_current_user
from backend.dependencies import get_db

router = APIRouter(prefix='/analytics/ozon-finance', tags=['Ozon Finance'])


def organization(db):
    oid = db.execute(text("SELECT nullif(current_setting('app.organization_id',true),'')::integer")).scalar()
    if not oid:
        raise HTTPException(401,'Требуется организация')
    return oid


@router.get('/days')
def daily(request:Request, date_from:date, date_to:date, db:Session=Depends(get_db)):
    require_current_user(request)
    if date_to < date_from or (date_to-date_from).days > 366:
        raise HTTPException(422,'Некорректный диапазон')
    oid=organization(db)
    rows=db.execute(text('''SELECT day,status,row_count,total_amount,last_error,updated_at
          FROM ozon_finance_days WHERE organization_id=:o AND day BETWEEN :a AND :b
          ORDER BY day DESC'''),{'o':oid,'a':date_from,'b':date_to}).mappings()
    return {'items':[dict(x) for x in rows], 'total_is_signed_accruals':True,
            'warning':'До завершения всех дней периода сумма не окончательная. Не является банковской выплатой.'}


@router.get('/categories')
def categories(request:Request, date_from:date, date_to:date, db:Session=Depends(get_db)):
    require_current_user(request)
    if date_to < date_from or (date_to-date_from).days > 366:
        raise HTTPException(422,'Некорректный диапазон')
    oid=organization(db)
    rows=db.execute(text('''SELECT category, count(*) AS operations,
          sum(amount) AS signed_amount FROM ozon_finance_accruals
          WHERE organization_id=:o AND day BETWEEN :a AND :b
          GROUP BY category ORDER BY category'''), {'o':oid,'a':date_from,'b':date_to}).mappings()
    incomplete = db.execute(text('''SELECT count(*) FROM ozon_finance_days
          WHERE organization_id=:o AND day BETWEEN :a AND :b AND status<>'complete' '''),
          {'o':oid,'a':date_from,'b':date_to}).scalar()
    return {'items':[dict(x) for x in rows], 'known_incomplete_days':incomplete,
            'warning':'ITEM/POSTING/NON_ITEM — технические категории, не готовые классы штрафов или расходов.'}

@router.get('/days/{report_day}/breakdown')
def daily_breakdown(report_day:date, request:Request, category:str|None=None,
                    limit:int=200, offset:int=0, db:Session=Depends(get_db)):
    """Read-only accounting rows. 'category' is Ozon's technical category, NOT fee type."""
    require_current_user(request)
    if category is not None and category not in ('ITEM','POSTING','NON_ITEM'):
        raise HTTPException(422,'Неизвестная категория начислений')
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(422,'Некорректная пагинация')
    oid=organization(db)
    state=db.execute(text('''SELECT day,status,row_count,total_amount,last_error
        FROM ozon_finance_days WHERE organization_id=:o AND day=:d'''),
        {'o':oid,'d':report_day}).mappings().first()
    if not state:
        raise HTTPException(404,'Данные за день ещё не загружены')
    params={'o':oid,'d':report_day,'cat':category,'lim':limit,'off':offset}
    groups=db.execute(text('''SELECT category, count(*) AS operations,
      coalesce(sum(amount),0) AS signed_amount FROM ozon_finance_accruals
      WHERE organization_id=:o AND day=:d GROUP BY category ORDER BY category'''),params).mappings()
    count=db.execute(text('''SELECT count(*) FROM ozon_finance_accruals
      WHERE organization_id=:o AND day=:d AND (:cat IS NULL OR category=:cat)'''),params).scalar()
    rows=db.execute(text('''SELECT accrual_id,accrued_at,category,unit_number,posting_number,
        amount,currency FROM ozon_finance_accruals
        WHERE organization_id=:o AND day=:d AND (:cat IS NULL OR category=:cat)
        ORDER BY accrual_id DESC LIMIT :lim OFFSET :off'''),params).mappings()
    return {'day':str(report_day),'status':state['status'],
            'stored_count':state['row_count'],'total_amount':state['total_amount'],
            'groups':[dict(x) for x in groups], 'items':[dict(x) for x in rows],
            'total_items':count,'limit':limit,'offset':offset,
            'note':'Категории ITEM/POSTING/NON_ITEM технические. unit_number не гарантирует артикул продавца.'}

# Codes verified against Ozon's 135-type catalog for 19–25 October 2026.
# Unknown codes are not guessed: label them using ID until audited.
OZON_FEE_NAMES = {
    '32': 'Логистика', '3': 'Продвижение бренда', '1': 'Эквайринг',
    '59': 'Обратная логистика', '17': 'Обработка Drop-off партнёрами',
    '29': 'Доставка до места выдачи', '98': 'Доставка до ПВЗ силами Ozon',
    '25': 'Товарная компенсация', '41': 'Оплата за клик',
    '45': 'Обработка возвратов партнёрами', '46': 'Размещение на складах Ozon',
    '39': 'Упаковка партнёрами', '38': 'Материалы для упаковки',
    '92': 'Штраф: жалобы покупателей', '84': 'Дополнительная упаковка Ozon',
    '15': 'Утилизация', '16': 'Обработка Drop-off',
    '94': 'Штраф: отгрузка в нерекомендованный слот',
    '79': 'Временное размещение у партнёров',
    '71': 'Услуги по вывозу товаров FBO (проверить официальное описание)',
}


def _fees_in(node):
    if isinstance(node, dict):
        if 'type_id' in node and isinstance(node.get('accrued'), dict):
            yield node
            return
        for value in node.values():
            yield from _fees_in(value)
    elif isinstance(node, list):
        for value in node:
            yield from _fees_in(value)


def _money_field(node):
    """A finance Money object, or a scalar; missing fields never fabricated."""
    from decimal import Decimal, InvalidOperation
    if isinstance(node, dict):
        node = node.get('amount')
    if node is None:
        return None
    try:
        d = Decimal(str(node))
        return d if d.is_finite() else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def _product_nodes(posting):
    if not isinstance(posting, dict):
        return []
    return [p for p in (posting.get('products') or []) if isinstance(p, dict)]


@router.get('/days/{report_day}/reasons')
def daily_reasons(report_day:date, request:Request, db:Session=Depends(get_db)):
    """Auditable partial decomposition of Ozon total_amount, no double subtraction.

    posting.products[].commission is included in total_amount, so its fields
    are split out and the remainder stays as an explicitly named balance.
    The seller_price value is NOT necessarily the entire 'Sales and returns'
    group shown in Ozon's Excel (loyalty/discount subcomponents can differ).
    """
    from collections import defaultdict
    from decimal import Decimal, InvalidOperation
    require_current_user(request)
    oid=organization(db)
    state=db.execute(text("""SELECT status,row_count,total_amount FROM ozon_finance_days
       WHERE organization_id=:o AND day=:d"""), {'o':oid,'d':report_day}).mappings().first()
    if not state:
        raise HTTPException(404,'Данные за день ещё не загружены')
    rows=db.execute(text("""SELECT accrual_id,category,unit_number,posting_number,amount,
        item_fees,non_item_fee,container_fees,posting FROM ozon_finance_accruals
        WHERE organization_id=:o AND day=:d ORDER BY accrual_id"""), {'o':oid,'d':report_day}).mappings().all()

    # Only exact and unambiguous SKU-to-offer mappings from the seller's own orders.
    skus=set()
    for r in rows:
        for product in _product_nodes(r['posting']):
            sku=product.get('sku')
            if sku is not None:
                skus.add(str(sku))
        item=r['item_fees']
        if isinstance(item,dict):
            for grp in item.get('fees') or []:
                if isinstance(grp,dict) and grp.get('sku') is not None:
                    skus.add(str(grp['sku']))
    sku_to_offer={}
    if skus:
        # Catalog is intentionally NOT guessed from nmId/offer-like strings.
        # Order-line SKU matching must be exact; store multi-valued matches as ambiguous.
        for i in range(0,len(skus),400):
            for r in db.execute(text("""SELECT sku,offer_id FROM ozon_order_lines
                 WHERE organization_id=:o AND sku::text = ANY(:skus)"""),
                 {'o':oid,'skus':list(sorted(skus))[i:i+400]}).mappings():
                sku_to_offer.setdefault(str(r['sku']),set()).add(str(r['offer_id'] or ''))

    groups=defaultdict(lambda:{'amount':Decimal('0'),'operations':0})
    kinds=defaultdict(lambda:{'amount':Decimal('0'),'operations':0})
    products=defaultdict(lambda:{'amount':Decimal('0'),'operations':0})
    sum_raw=Decimal('0')
    split_count=0
    unassigned=Decimal('0')

    def add(group,kind,sku,amount):
        if not amount:
            return
        sku=str(sku or '')
        candidate=sku_to_offer.get(sku,set())
        article=next(iter(candidate)) if len(candidate)==1 and next(iter(candidate)) else ''
        for bucket,key in ((groups,group),(kinds,(group,kind)),(products,(group,kind,article))):
            bucket[key]['amount']+=amount
            bucket[key]['operations']+=1

    fee_groups={
        '32':'Услуги доставки','59':'Услуги доставки','29':'Услуги партнёров','98':'Услуги доставки',
        '1':'Услуги партнёров','17':'Услуги партнёров','45':'Услуги партнёров',
        '39':'Услуги партнёров','38':'Другие услуги и штрафы','16':'Услуги доставки',
        '79':'Услуги партнёров','3':'Продвижение и реклама','41':'Продвижение и реклама',
        '46':'Услуги FBO','84':'Услуги FBO','71':'Услуги FBO',
        '92':'Другие услуги и штрафы','94':'Другие услуги и штрафы','15':'Другие услуги и штрафы',
        '25':'Компенсации и декомпенсации'
    }
    catalog = {str(r['type_id']): r['description'] or r['name'] for r in db.execute(text("SELECT type_id, name, description FROM ozon_finance_type_catalog WHERE organization_id=:o"), {'o':oid}).mappings()}
    for r in rows:
        raw=Decimal(str(r['amount']))
        sum_raw+=raw
        explained=Decimal('0')
        posting=r['posting']
        prod_nodes=_product_nodes(posting)
        sale_lines=[]
        for prod in prod_nodes:
            com=prod.get('commission') or {}
            if not isinstance(com,dict):
                continue
            sku=prod.get('sku')
            sold=_money_field(com.get('seller_price'))
            sale_amount=_money_field(com.get('sale_amount'))
            commission=_money_field(com.get('sale_commission'))
            sale_lines.append((sku,sold,sale_amount))
            if commission is not None:
                explained+=commission
                add('Вознаграждение Ozon','Комиссия за продажу',sku,commission)
        # Fee records may describe several SKUs within the same accrual.
        item_groups=(r['item_fees'] or {}).get('fees') or [] if isinstance(r['item_fees'],dict) else []
        for group in item_groups:
            if not isinstance(group,dict): continue
            sku=group.get('sku')
            for fee in _fees_in(group.get('fees') or []):
                money=_money_field(fee.get('accrued'))
                if money is None: continue
                tid=str(fee['type_id'])
                explained+=money
                add(fee_groups.get(tid,'Прочие начисления'),catalog.get(tid, f'Тип начисления {tid} (справочник не загружен)'),sku,money)
        # Other expenses not linked to an individual SKU.
        for fee in _fees_in([r['non_item_fee'],r['container_fees']]):
            money=_money_field(fee.get('accrued'))
            if money is None: continue
            tid=str(fee['type_id'])
            explained+=money
            add(fee_groups.get(tid,'Прочие начисления'),catalog.get(tid, f'Тип начисления {tid} (справочник не загружен)'),None,money)
        # Posting delivery may include nested product delivery services not above.
        for prod in prod_nodes:
            d=prod.get('delivery') or {}
            if not isinstance(d,dict): continue
            for fee in _fees_in(d.get('services') or []):
                money=_money_field(fee.get('accrued'))
                if money is None:continue
                tid=str(fee['type_id'])
                explained+=money
                add(fee_groups.get(tid,'Прочие начисления'),catalog.get(tid, f'Тип начисления {tid} (справочник не загружен)'),prod.get('sku'),money)
        # Compare BOTH alternatives only after commission and all known fees have
        # been included. Choose sale_amount only if it reconciles this accrual
        # precisely and seller_price does not. Never use a global replacement.
        usable=bool(sale_lines) and all(
            seller is not None and actual is not None
            for _,seller,actual in sale_lines
        )
        seller_sum=sum((seller for _,seller,_ in sale_lines if seller is not None),Decimal('0'))
        actual_sum=sum((actual for _,_,actual in sale_lines if actual is not None),Decimal('0'))
        base_diff=raw-explained-seller_sum
        alternative_diff=raw-explained-actual_sum
        use_sale_amount=(usable and abs(base_diff)>Decimal('0.01')
                         and abs(alternative_diff)<=Decimal('0.01'))
        for sku,seller,actual in sale_lines:
            sold=actual if use_sale_amount else seller
            if sold is not None:
                explained+=sold
                add('Продажи и возвраты',
                    'Сумма продажи (sale_amount)' if use_sale_amount else 'Стоимость товара (цена продавца)',
                    sku,sold)
                split_count+=1
        # Any unexplained difference remains visible; the total never changes.
        remainder=raw-explained
        if remainder:
            unassigned+=remainder
            add('Не распределено','Остаток начисления (требует сверки с Ozon)',None,remainder)

    group_items=[{'group':key,'operations':v['operations'],'amount':str(v['amount'])} for key,v in groups.items()]
    type_items=[{'group':g,'kind':k,'operations':v['operations'],'amount':str(v['amount'])} for (g,k),v in kinds.items()]
    # Names are resolved only after the exact SKU -> offer/article mapping above.
    # Match against this organization's master catalog; never infer a name from SKU.
    article_keys={str(a).strip().casefold() for _,_,a in products if str(a).strip()}
    names_by_article={}
    if article_keys:
        catalog_rows=db.execute(text("""
            SELECT seller_article, internal_article, name
            FROM master_products WHERE organization_id=:o
        """), {'o':oid}).mappings().all()
        candidates=defaultdict(set)
        for p in catalog_rows:
            name=str(p['name'] or '').strip()
            if not name:
                continue
            for field in ('seller_article','internal_article'):
                key=str(p[field] or '').strip().casefold()
                if key in article_keys:
                    candidates[key].add(name)
        names_by_article={k:next(iter(v)) for k,v in candidates.items() if len(v)==1}
    product_items=[{'group':g,'kind':k,'article':a,
                    'product_name':names_by_article.get(str(a).strip().casefold(),'') if a else '',
                    'operations':v['operations'],'amount':str(v['amount'])}
                   for (g,k,a),v in products.items()]
    for collection in (group_items,type_items,product_items):
        collection.sort(key=lambda v:-abs(Decimal(v['amount'])))
    grouped=sum((v['amount'] for v in groups.values()),Decimal('0'))
    return {'day':str(report_day),'status':state['status'],
            'accrual_total':str(sum_raw),'groups_total':str(grouped),
            'balanced':sum_raw==grouped,'groups':group_items,
            'types':type_items,'articles':product_items,
            'unassigned_amount':str(unassigned),'split_products':split_count,
            'note':'Продажи и комиссия выделены из posting.products.commission; услуги из типизированных fee. Нераспределённый остаток сохраняет точный итог. Баллы за скидки и программы партнёров пока не подтверждены по структуре API, поэтому не выделяются как готовые показатели. Артикулы — только при однозначной связи SKU с заказами.'}


@router.get('/weeks')
def weekly(request:Request, date_from:date, date_to:date, db:Session=Depends(get_db)):
    require_current_user(request)
    if date_to < date_from or (date_to-date_from).days > 730:
        raise HTTPException(422,'Некорректный диапазон')
    oid=organization(db)
    # Financial accrual weeks here are calendar Mon-Sun buckets, NOT official Ozon payment reports.
    items=db.execute(text("""
        SELECT (date_trunc('week',day::timestamp))::date AS date_from,
               (date_trunc('week',day::timestamp)+interval '6 days')::date AS date_to,
               count(*) AS loaded_days, count(*) FILTER (WHERE status='complete') AS complete_days,
               coalesce(sum(total_amount),0) AS total_amount,
               coalesce(sum(row_count),0) AS row_count
        FROM ozon_finance_days
        WHERE organization_id=:o AND day>=:a_minus AND day<=:b_plus
        GROUP BY 1,2 HAVING (date_trunc('week',day::timestamp))::date<=:b
            AND (date_trunc('week',day::timestamp)+interval '6 days')::date>=:a
        ORDER BY date_from DESC
    """),{'o':oid,'a':date_from,'b':date_to,
           'a_minus':date_from - __import__('datetime').timedelta(days=6),
           'b_plus':date_to + __import__('datetime').timedelta(days=6)}).mappings()
    data=[]
    from datetime import timedelta
    for row in items:
        item=dict(row)
        period_end=min(item['date_to'],date.today()-timedelta(days=2))
        expected=max(0,(period_end-item['date_from']).days+1)
        item['expected_days']=expected
        item['status']='complete' if expected==7 and item['complete_days']==7 else 'partial'
        data.append(item)
    return {'items':data,'note':'Недели рассчитаны из дневных начислений (понедельник–воскресенье). Не являются официальными платёжными периодами Ozon.'}


@router.get('/weeks/{week_start}/reasons')
def weekly_reasons(week_start:date, request:Request, db:Session=Depends(get_db)):
    from datetime import timedelta
    from decimal import Decimal
    from collections import defaultdict
    require_current_user(request)
    if week_start.weekday()!=0:
        raise HTTPException(422,'Начало недели должно быть понедельником')
    oid=organization(db)
    days=db.execute(text("SELECT day,status FROM ozon_finance_days WHERE organization_id=:o AND day BETWEEN :a AND :b ORDER BY day"),
                     {'o':oid,'a':week_start,'b':week_start+timedelta(days=6)}).mappings().all()
    if not days:raise HTTPException(404,'Неделя ещё не загружена')
    groups=defaultdict(lambda:[Decimal('0'),0]); types=defaultdict(lambda:[Decimal('0'),0]); articles=defaultdict(lambda:[Decimal('0'),0])
    total=Decimal('0'); balanced=True
    for day in days:
        result=daily_reasons(day['day'],request,db)
        total+=Decimal(result['accrual_total'])
        balanced=balanced and result['balanced']
        for x in result['groups']:
            target=groups[x['group']];target[0]+=Decimal(x['amount']);target[1]+=x['operations']
        for x in result['types']:
            target=types[(x['group'],x['kind'])];target[0]+=Decimal(x['amount']);target[1]+=x['operations']
        for x in result['articles']:
            target=articles[(x['group'],x['kind'],x['article'],x['product_name'])];target[0]+=Decimal(x['amount']);target[1]+=x['operations']
    return {'date_from':str(week_start),'date_to':str(week_start+timedelta(days=6)),
            'accrual_total':str(total),'status':'complete' if len(days)==7 and all(x['status']=='complete' for x in days) else 'partial',
            'balanced':balanced,
            'groups':[{'group':k,'amount':str(v[0]),'operations':v[1]} for k,v in sorted(groups.items())],
            'types':[{'group':k[0],'kind':k[1],'amount':str(v[0]),'operations':v[1]} for k,v in sorted(types.items())],
            'articles':[{'group':k[0],'kind':k[1],'article':k[2],'product_name':k[3], 'amount':str(v[0]),'operations':v[1]} for k,v in sorted(articles.items())],
            'note':'Суммирование дневных начислений, без повторного учёта вложенных услуг. Отчёт частичный, пока не загружены все семь дней.'}
