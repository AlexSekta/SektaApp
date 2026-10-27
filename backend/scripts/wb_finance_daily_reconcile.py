"""Recheck completed WB daily Finance detail from DB only; no API requests.

Usage: python -m backend.scripts.wb_finance_daily_reconcile --org 2
"""
import argparse
from decimal import Decimal
from sqlalchemy import text
from backend.services import wb_finance_worker as weekly


def run(org: int):
    db = weekly.context(org)
    updated = 0
    try:
        reports = db.execute(text("""SELECT report_id, expected_retail, expected_for_pay,
          expected_logistics, expected_penalty, expected_deduction, status
          FROM wb_finance_daily_reports WHERE organization_id=:o AND status='mismatch'
          ORDER BY report_date DESC, report_id"""), {'o': org}).mappings().all()
        for r in reports:
            totals = db.execute(text("""SELECT count(*) AS n,
                coalesce(sum(CASE WHEN lower(btrim(operation))='возврат' THEN -retail ELSE retail END),0) AS retail,
                coalesce(sum(CASE WHEN lower(btrim(operation))='возврат' THEN -for_pay ELSE for_pay END),0) AS for_pay,
                coalesce(sum(logistics),0) AS logistics,
                coalesce(sum(penalty),0) AS penalty,
                coalesce(sum(deduction),0) AS deduction
                FROM wb_finance_daily_entries WHERE organization_id=:o AND report_id=:r"""), {'o':org,'r':r['report_id']}).mappings().one()
            checks = [('expected_retail','retail'),('expected_for_pay','for_pay'),
                      ('expected_logistics','logistics'),('expected_penalty','penalty'),
                      ('expected_deduction','deduction')]
            mismatch = [expected for expected, actual in checks
                        if r[expected] is not None and abs(Decimal(r[expected]) - Decimal(totals[actual])) > Decimal('0.02')]
            status = 'mismatch' if mismatch else 'complete'
            print(f"WB_DAILY_RECHECK report={r['report_id']} rows={totals['n']} status={status} mismatches={','.join(mismatch) or '-'}")
            db.execute(text("""UPDATE wb_finance_daily_reports
                SET status=:s,last_error=:e,updated_at=now()
                WHERE organization_id=:o AND report_id=:r AND status='mismatch'"""),
                {'s':status,'e':('Несоответствие: '+', '.join(mismatch)) if mismatch else None,
                 'o':org,'r':r['report_id']})
            updated += 1
        db.commit()
        print(f'WB_DAILY_RECHECK_DONE reports={updated} source=database')
    except Exception:
        db.rollback()
        raise
    finally:
        weekly.close(db)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--org', type=int, required=True)
    args = parser.parse_args()
    run(args.org)
