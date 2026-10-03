import pandas as pd
import datetime
import logging
import csv
import io
import xml.etree.ElementTree as ET
import models
from sqlalchemy.orm import Session
from utils import clean_numeric


def _count_csv_fields(line: str) -> int:
    """Return number of comma-separated fields in a CSV line (respects quotes)."""
    try:
        reader = csv.reader(io.StringIO(line))
        return len(next(reader))
    except Exception:
        return 0


def _detect_csv_format(file_path):
    """Detect whether a CSV is the detailed settlement or Transaction View format."""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = []
        for _ in range(100):
            line = f.readline()
            if not line:
                break
            lines.append(line)

    # Match 'date/time' only on lines that are actual CSV headers (>=3 fields)
    header_idx = next((i for i, line in enumerate(lines)
                       if 'date/time' in line.lower()
                       and _count_csv_fields(line) >= 3), None)
    if header_idx is not None:
        return 'detailed', header_idx

    # Metadata lines like "Date/Time: Posted ..." have 1 field; skip them.
    # Only match if the line has >=3 fields (real CSV header).
    if lines and 'date' in lines[0].lower() and _count_csv_fields(lines[0]) >= 3:
        return 'transaction_view', 0

    raise ValueError(
        f"Cannot detect CSV format in {file_path}. "
        f"First few lines: {lines[:3]}")


def sync_settlement_csv(file_path, db_session: Session, month_start=None, month_end=None, is_deferred=False):
    """Parse Settlement or Deferred CSV and insert into FinancialEvent table.

    - Auto-detects date range from CSV data for scoped deletion.
    - When month_start/month_end are given, uses those as fallback.
    - Returns count of new records inserted.
    """
    fmt, header_idx = _detect_csv_format(file_path)

    if fmt == 'detailed':
        df = pd.read_csv(file_path, skiprows=header_idx, encoding='utf-8-sig')
        df.columns = [c.strip().lower() for c in df.columns]
        for col in ['product sales', 'selling fees', 'fba fees', 'other transaction fees', 'promotional rebates', 'total']:
            if col in df.columns:
                df[col] = df[col].apply(clean_numeric)
    elif fmt == 'transaction_view':
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        df.columns = [c.strip().lower() for c in df.columns]
        for col in ['total product charges', 'total promotional rebates', 'amazon fees', 'other', 'total (inr)']:
            if col in df.columns:
                df[col] = df[col].apply(clean_numeric)
    else:
        raise ValueError(f"Unknown CSV format for {file_path}")

    # Auto-detect date range from CSV data
    csv_dates = []
    date_col = 'date/time' if 'date/time' in df.columns else 'date'
    if date_col in df.columns:
        for val in df[date_col]:
            try:
                csv_dates.append(pd.to_datetime(val, format='mixed', dayfirst=True).date())
            except Exception:
                pass

    if csv_dates:
        csv_start = min(csv_dates)
        csv_end = max(csv_dates)
    elif month_start and month_end:
        csv_start = month_start
        csv_end = month_end
    else:
        csv_start = None
        csv_end = None

    # Scoped delete: wipe records in the auto-detected date range
    if csv_start and csv_end:
        db_session.query(models.FinancialEvent).filter(
            models.FinancialEvent.posted_date >= csv_start,
            models.FinancialEvent.posted_date <= csv_end,
            models.FinancialEvent.is_deferred == is_deferred
        ).delete()

    inserted = 0
    for _, row in df.iterrows():
        order_id = str(row.get('order id', '')).strip()
        if not order_id or order_id.lower() == 'nan' or order_id in ('---', '-', ''):
            # For Transfer/non-order rows, use settlement id as key
            order_id = str(row.get('settlement id', '')).strip()
            if not order_id or order_id.lower() == 'nan':
                continue

        # --- SKU ---
        if fmt == 'detailed':
            sku = str(row.get('sku', '')).strip()
            if not sku or sku.lower() == 'nan':
                sku = 'SERVICE_FEE'
        else:
            sku = 'UNKNOWN'

        # --- Date ---
        date_val = row.get('date/time', row.get('date', ''))
        try:
            posted_date = pd.to_datetime(date_val, format='mixed', dayfirst=True).date()
        except Exception:
            posted_date = datetime.date.today()
            logging.warning(f"Could not parse date '{date_val}' for order {order_id} — using today")

        # --- Event type ---
        if fmt == 'detailed':
            raw_type = str(row.get('type', 'Order')).strip()
            if 'reimbursement' in raw_type.lower():
                event_type = 'Reimbursement'
            elif 'refund' in raw_type.lower():
                event_type = 'Refund'
            elif 'transfer' in raw_type.lower():
                event_type = 'Transfer'
            elif 'shipping services' in raw_type.lower():
                event_type = 'ShippingService'
            elif raw_type.lower() == 'order':
                event_type = 'Order'
            else:
                event_type = 'Other'
        else:
            raw_type = str(row.get('transaction type', '')).strip().lower()
            if 'refund' in raw_type:
                event_type = 'Refund'
            elif 'order' in raw_type:
                event_type = 'Order'
            elif 'transfer' in raw_type:
                event_type = 'Transfer'
            else:
                event_type = 'Other'

        is_refund = event_type == 'Refund'
        is_reimbursement = event_type == 'Reimbursement'

        # --- Financials ---
        if fmt == 'detailed':
            product_sales = clean_numeric(row.get('product sales', 0.0))
            fba_fees      = clean_numeric(row.get('fba fees', 0.0))
            selling_fees  = clean_numeric(row.get('selling fees', 0.0))
            other_fees    = clean_numeric(row.get('other transaction fees', 0.0))
            total_amt     = clean_numeric(row.get('total', 0.0))
            rebates       = clean_numeric(row.get('promotional rebates', 0.0))
            qty_raw       = row.get('quantity', 0)
            quantity      = int(qty_raw) if not pd.isna(qty_raw) and str(qty_raw).strip() not in ('', 'nan') else 0
        else:
            product_sales     = clean_numeric(row.get('total product charges', 0.0))
            rebates           = clean_numeric(row.get('total promotional rebates', 0.0))
            fba_fees          = 0.0
            selling_fees      = clean_numeric(row.get('amazon fees', 0.0))
            other_fees        = clean_numeric(row.get('other', 0.0))
            total_amt         = clean_numeric(row.get('total (inr)', 0.0))
            quantity          = 1 if event_type == 'Order' else 0

        # For Transfer rows, total_amt is the disbursement amount
        description = str(row.get('description', '')).strip() if fmt == 'detailed' else ''

        new_event = models.FinancialEvent(
            amazon_order_id=order_id,
            posted_date=posted_date,
            sku=sku,
            event_type=event_type,
            description=description,
            quantity=quantity if not is_refund else 0,
            product_sales=product_sales if not (is_refund or is_reimbursement) else 0.0,
            fba_fees=fba_fees,
            selling_fees=selling_fees,
            other_fees=other_fees,
            total_amount=total_amt,
            promotional_rebates=rebates,
            is_deferred=is_deferred
        )
        db_session.add(new_event)
        inserted += 1

    return inserted


def sync_ads_report(file_path, db_session: Session, month_start=None):
    """Parse Ads XLSX and store per-campaign rows + total spend as OperatingExpense."""
    if file_path.endswith('.xlsx'):
        df = pd.read_excel(file_path)
    else:
        df = pd.read_csv(file_path)

    df.columns = [c.strip() for c in df.columns]

    spend_col = next((c for c in df.columns if 'spend' in c.lower() and 'acos' not in c.lower()), None)
    if not spend_col:
        raise ValueError(f"No 'spend' column found in ads report ({file_path})")

    df[spend_col] = df[spend_col].apply(clean_numeric)
    total_spend = round(df[spend_col].sum(), 2)

    # Store per-campaign rows in AdsMetric table
    if month_start:
        db_session.query(models.AdsMetric).filter(
            models.AdsMetric.report_month == month_start
        ).delete()

    def find_column(patterns, default):
        for col in df.columns:
            col_lower = col.lower()
            if any(p.lower() in col_lower for p in patterns):
                return col
        return default

    numeric_cols = {
        'impressions': find_column(['impressions'], 'Impressions'),
        'clicks': find_column(['clicks'], 'Clicks'),
        'ctr': find_column(['click-through rate', 'ctr'], 'Click-Through Rate (CTR)'),
        'spend': spend_col,
        'sales_7d': find_column(['7 day total sales', 'sales'], '7 Day Total Sales (₹)'),
        'acos': find_column(['advertising cost of sales', 'acos'], 'Total Advertising Cost of Sales (ACOS) '),
        'roas': find_column(['return on advertising spend', 'roas'], 'Total Return on Advertising Spend (ROAS)'),
        'orders_7d': find_column(['7 day total orders', 'orders'], '7 Day Total Orders (#)'),
        'units_7d': find_column(['7 day total units', 'units'], '7 Day Total Units (#)'),
        'cvr': find_column(['conversion rate', 'cvr'], '7 Day Conversion Rate'),
    }

    for _, row in df.iterrows():
        campaign = str(row.get('Campaign Name', '')).strip()
        if not campaign or campaign.lower() == 'nan':
            continue
        kw = str(row.get('Customer Search Term', '')).strip()
        date_val = row.get('Date', month_start)
        try:
            row_date = pd.to_datetime(date_val).date()
        except Exception:
            row_date = month_start or datetime.date.today()

        def g(col_key):
            col = numeric_cols.get(col_key, '')
            if col in df.columns:
                return clean_numeric(row.get(col, 0.0))
            return 0.0

        # SKU/Brand Extraction Heuristic
        sku_found = None
        brand_found = None
        if ' - ' in campaign:
            parts = [p.strip() for p in campaign.split(' - ')]
            for p in parts:
                if p.startswith('B0') and len(p) == 10:
                    sku_found = p
                    break
            if not sku_found and len(parts) > 0:
                brand_found = parts[0]
        else:
            brand_found = campaign.split('-')[0].strip()

        metric = models.AdsMetric(
            report_month=month_start or row_date,
            date=row_date,
            campaign_name=campaign,
            search_term=kw,
            impressions=int(g('impressions')),
            clicks=int(g('clicks')),
            ctr=g('ctr'),
            spend=g('spend'),
            sales_7d=g('sales_7d'),
            acos=g('acos'),
            roas=g('roas'),
            orders_7d=int(g('orders_7d')),
            units_7d=int(g('units_7d')),
            cvr=g('cvr'),
            sku=sku_found,
            brand=brand_found,
        )
        db_session.add(metric)

    # Upsert total spend as OperatingExpense
    if total_spend > 0 and month_start:
        existing = db_session.query(models.OperatingExpense).filter(
            models.OperatingExpense.category == 'Amazon Ads',
            models.OperatingExpense.date_incurred == month_start
        ).first()
        if existing:
            existing.amount = total_spend
        else:
            db_session.add(models.OperatingExpense(
                category='Amazon Ads',
                amount=total_spend,
                date_incurred=month_start,
                description='Sponsored Products ad spend from uploaded report'
            ))

    return total_spend


def sync_business_csv(file_path, db_session: Session = None, month_start=None):
    """Parse Business Report CSV, store SKU-level session data, return summary metrics.

    Handles both standard SKU-level reports and irregular dashboard-exports
    gracefully (returns zeros and logs a warning when expected columns are missing).
    """
    try:
        df = pd.read_csv(file_path, on_bad_lines='skip')
    except Exception:
        try:
            df = pd.read_csv(file_path, encoding='utf-8-sig', on_bad_lines='skip')
        except Exception as e:
            raise ValueError(
                f"Business report is not a valid CSV: {e}") from e

    df.columns = [c.strip() for c in df.columns]

    # Guard: if the essential columns don't exist, this is the wrong file type
    has_sku_data = 'SKU' in df.columns and 'Units Ordered' in df.columns
    if not has_sku_data:
        logging.warning(
            f"Business report at {file_path} lacks SKU-level columns "
            f"(columns found: {list(df.columns)[:10]}…); returning empty summary")
        return {"units_ordered": 0, "sessions": 0, "page_views": 0, "conversion_pct": 0.0}

    for col in ['Units Ordered', 'Sessions - Total', 'Page Views - Total']:
        if col in df.columns:
            df[col] = df[col].apply(clean_numeric)

    if 'Unit Session Percentage' in df.columns:
        df['Unit Session Percentage'] = df['Unit Session Percentage'].apply(
            lambda x: clean_numeric(str(x).replace('%', ''))
        )

    units    = df['Units Ordered'].sum() if 'Units Ordered' in df.columns else 0
    sessions = df['Sessions - Total'].sum() if 'Sessions - Total' in df.columns else 0
    page_views = df['Page Views - Total'].sum() if 'Page Views - Total' in df.columns else 0
    conv_pct = round((units / sessions * 100), 2) if sessions > 0 else 0.0

    # Store per-SKU session data
    if db_session and month_start:
        db_session.query(models.BusinessMetric).filter(
            models.BusinessMetric.report_month == month_start
        ).delete()

        for _, row in df.iterrows():
            sku = str(row.get('SKU', '')).strip()
            if not sku or sku.lower() == 'nan':
                continue
            bm = models.BusinessMetric(
                report_month=month_start,
                sku=sku,
                asin=str(row.get('(Child) ASIN', '')).strip(),
                title=str(row.get('Title', '')).strip()[:255],
                sessions=int(clean_numeric(row.get('Sessions - Total', 0))),
                page_views=int(clean_numeric(row.get('Page Views - Total', 0))),
                units_ordered=int(clean_numeric(row.get('Units Ordered', 0))),
                unit_session_pct=clean_numeric(str(row.get('Unit Session Percentage', 0)).replace('%', '')),
                ordered_product_sales=clean_numeric(row.get('Ordered Product Sales', 0)),
            )
            db_session.add(bm)

    return {
        "units_ordered": int(units),
        "sessions": int(sessions),
        "page_views": int(page_views),
        "conversion_pct": conv_pct
    }


def sync_returns_xml(file_path, db_session: Session = None, month_start=None):
    """Parse Amazon Returns XML and return count of return items."""
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception as e:
        raise ValueError(f"Returns report is not a valid XML: {e}") from e

    count = 0
    for msg in root.iter('Message'):
        for rd in msg.iter('return_details'):
            for item in rd.iter('item_details'):
                count += 1

    if count == 0:
        for msg in root.iter('Message'):
            for item in msg.iter('item_details'):
                count += 1

    logging.info(f"Returns XML: {count} return items found in {file_path}")
    return count



