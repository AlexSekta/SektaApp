"""Daily WB Finance, called by the existing single Finance worker. No new threads or API credentials."""
import logging
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import text
from backend.services import wb_finance_worker as weekly

log = logging.getLogger('wb_finance_daily')

def money(value):
    return Decimal(str(value or 0))

def discover(org):
    db = weekly.context(org)
    try:
        # Only finished days. A single list request covers the newest 14 days.
        end = date.today()-timedelta(days=1)
        start = end-timedelta(days=13)
        reports = weekly.finance_request(db, '/api/finance/v1/sales-reports/list',
            {'dateFrom':start.isoformat(),'dateTo':end.isoformat(),'period':'daily','limit':1000,'offset':0})
        if reports is None: return
        if len(reports)>=1000: raise RuntimeError('Daily report list pagination required')
        for r in reports:
            if not r.get('reportId'): continue
            db.execute(text('''INSERT INTO wb_finance_daily_reports
            (organization_id,report_id,report_date,report_type,created_date,expected_retail,expected_for_pay,
             expected_bank_payment,expected_logistics,expected_penalty,expected_deduction,expected_storage,expected_acceptance)
            VALUES (:o,:id,:dt,:type,:created,:ret,:pay,:bank,:log,:pen,:ded,:st,:acc)
            ON CONFLICT (organization_id,report_id) DO UPDATE SET
              expected_retail=EXCLUDED.expected_retail,expected_for_pay=EXCLUDED.expected_for_pay,
              expected_bank_payment=EXCLUDED.expected_bank_payment,expected_logistics=EXCLUDED.expected_logistics,
              expected_penalty=EXCLUDED.expected_penalty,expected_deduction=EXCLUDED.expected_deduction,
              expected_storage=EXCLUDED.expected_storage,expected_acceptance=EXCLUDED.expected_acceptance'''),
            {'o':org,'id':int(r['reportId']),'dt':r['dateFrom'],'type':r.get('reportType'),
             'created':r.get('createDate') or None,'ret':money(r.get('retailAmountSum')),
             'pay':money(r.get('forPaySum')),'bank':money(r.get('bankPaymentSum')),
             'log':money(r.get('deliveryServiceSum')),'pen':money(r.get('penaltySum')),
             'ded':money(r.get('deductionSum')),'st':money(r.get('paidStorageSum')),
             'acc':money(r.get('paidAcceptanceSum'))})
        db.commit()
        log.info('WB_DAILY_DISCOVER_OK org=%s reports=%s',org,len(reports))
    except Exception as exc:
        db.rollback()
        log.warning('WB_DAILY_DISCOVER_RETRY org=%s type=%s',org,type(exc).__name__)
    finally: weekly.close(db)

def work_one(org, rid):
    db=weekly.context(org)
    try:
        job=db.execute(text('''SELECT cursor_rrd,expected_retail,expected_for_pay,expected_logistics,expected_penalty,expected_deduction
        FROM wb_finance_daily_reports WHERE organization_id=:o AND report_id=:r'''),{'o':org,'r':rid}).mappings().first()
        if not job: return
        cursor=int(job['cursor_rrd'])
        data=weekly.finance_request(db,f'/api/finance/v1/sales-reports/detailed/{rid}',{'limit':1000,'rrdId':cursor,'fields':[]})
        if data is None: raise RuntimeError('Finance API returned no usable response')
        if len(data)>1000: raise RuntimeError('Unexpected page length')
        ids=[int(r['rrdId']) for r in data]
        if ids and (min(ids)<=cursor or len(ids)!=len(set(ids))): raise RuntimeError('Invalid daily pagination cursor')
        for r in data:
            fields={'o':org,'r':rid,'id':int(r['rrdId']),'nm':str(r.get('nmId') or '') or None,
                'v':str(r.get('vendorCode') or '') or None,'sku':str(r.get('sku') or '') or None,
                'srid':str(r.get('srid') or '') or None,
                'oper':str(r.get('sellerOperName') or '')[:250],
                'reason':str(r.get('bonusTypeName') or r.get('sellerOperName') or r.get('docTypeName') or 'Не указано')[:500]}
            for param,key in [('ret','retailAmount'),('pay','forPay'),('commission','ppvzSalesCommission'),
                ('vat','vwNds'),('acquiring','acquiringFee'),('logistics','deliveryService'),
                ('storage','paidStorage'),('acceptance','paidAcceptance'),('penalty','penalty'),
                ('deduction','deduction'),('additional','additionalPayment')]: fields[param]=money(r.get(key))
            db.execute(text('''INSERT INTO wb_finance_daily_entries
            (organization_id,report_id,rrd_id,nm_id,vendor_code,sku,srid,operation,reason,retail,for_pay,commission,vat,acquiring,logistics,storage,acceptance,penalty,deduction,additional_payment)
            VALUES (:o,:r,:id,:nm,:v,:sku,:srid,:oper,:reason,:ret,:pay,:commission,:vat,:acquiring,:logistics,:storage,:acceptance,:penalty,:deduction,:additional)
            ON CONFLICT (organization_id,report_id,rrd_id) DO NOTHING'''),fields)
        # WB detail expresses returns as positive magnitudes, while report totals
        # subtract them. Preserve the original source rows and sign them only in totals.
        sums=db.execute(text('''SELECT count(*),
          coalesce(sum(CASE WHEN lower(btrim(operation))='возврат' THEN -retail ELSE retail END),0),
          coalesce(sum(CASE WHEN lower(btrim(operation))='возврат' THEN -for_pay ELSE for_pay END),0),
          coalesce(sum(logistics),0),coalesce(sum(penalty),0),coalesce(sum(deduction),0)
        FROM wb_finance_daily_entries WHERE organization_id=:o AND report_id=:r'''),{'o':org,'r':rid}).first()
        if len(data)<1000:
            check=[('expected_retail',sums[1]),('expected_for_pay',sums[2]),('expected_logistics',sums[3]),
                  ('expected_penalty',sums[4]),('expected_deduction',sums[5])]
            mismatches=[name for name,value in check if job[name] is not None and abs(job[name]-value)>Decimal('0.02')]
            status='mismatch' if mismatches else 'complete'
            err=('Несоответствие: '+', '.join(mismatches)) if mismatches else None
        else:status='loading';err=None
        db.execute(text('''UPDATE wb_finance_daily_reports SET cursor_rrd=:c,loaded_rows=:n,status=:s,last_error=:e,updated_at=now()
        WHERE organization_id=:o AND report_id=:r'''),{'c':max(ids) if ids else cursor,'n':sums[0],'s':status,'e':err,'o':org,'r':rid})
        db.commit()
        log.info('WB_DAILY_PAGE_OK org=%s report=%s rows=%s total=%s status=%s',org,rid,len(data),sums[0],status)
    except Exception as exc:
        db.rollback()
        db.execute(text('''UPDATE wb_finance_daily_reports SET status='retry',last_error=:e,updated_at=now()
        WHERE organization_id=:o AND report_id=:r'''),{'e':type(exc).__name__,'o':org,'r':rid})
        db.commit()
        log.warning('WB_DAILY_PAGE_RETRY org=%s report=%s error=%s',org,rid,type(exc).__name__)
    finally: weekly.close(db)

def next_report(org):
    db=weekly.context(org)
    try:
        return db.execute(text('''SELECT report_id FROM wb_finance_daily_reports WHERE organization_id=:o
        AND status IN ('queued','loading','retry') ORDER BY report_date DESC,report_id DESC LIMIT 1'''),{'o':org}).scalar()
    finally:weekly.close(db)
