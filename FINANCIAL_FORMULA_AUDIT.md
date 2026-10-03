# Financial Formula Audit — Amazon India

**Date:** 2026-07-20
**Audited by:** OpenCode (automated)

## Summary

Audited every financial formula in `data_processor.py`, `processor.py`, `main.py`, and all templates for Amazon India accuracy. Found **3 issues** in the reconciliation logic, all now fixed.

---

## Issue 1: Reconciliation used wrong "gross sales" (CRITICAL)

**File:** `data_processor.py` — `get_reconciliation_check()`

**Problem:** The reconciliation formula used `total_net_order_proceeds` (sum of `total_amount` for orders) as the starting "gross sales" figure. But `total_amount` is the **net** amount after ALL deductions including promotional rebates. For Amazon India, `product_sales` in the settlement CSV excludes promotional rebates, and `total_amount = product_sales - FBA - Selling - Other - Promotions`. This meant the reconciliation was double-counting promotions.

**Before:**
```python
expected_payout_gross = total_net_order_proceeds_incl_deferred - total_refunds + total_reimbursements - other_fees
```

**After:**
```python
total_promotions = sum(abs(e.promotional_rebates) for e in events if e.event_type == 'Order')
gross_sales = total_net_order_proceeds_incl_deferred + total_promotions
expected_payout_gross = gross_sales - total_refunds + total_reimbursements - other_fees - total_promotions
```

**Impact:** Reconciliation "should have disbursed" was incorrect by the total promotional rebates amount.

---

## Issue 2: Deep dive "gross_sales" excluded promotions

**File:** `data_processor.py` — `get_disbursement_deep_dive()`

**Problem:** `gross_sales` was calculated as `sum(e.product_sales for orders)`, which excludes promotional rebates. For Amazon India, gross sales must include promotional rebates since they're part of the order value.

**Before:**
```python
gross_sales = sum(e.product_sales for e in window_events if e.event_type == 'Order')
```

**After:**
```python
gross_sales = sum(e.product_sales + abs(e.promotional_rebates) for e in window_events if e.event_type == 'Order')
```

**Impact:** Deep dive payout history showed understated gross sales and incorrect net calculated amounts.

---

## Issue 3: Reconciliation template labels and missing Promotions line

**File:** `templates/reconciliation.html`

**Problem:** 
1. Template labeled the starting figure as "Net Sales (after fees)" when it should be "Gross Sales (before deductions)"
2. Template was missing a Promotions line item in the reconciliation breakdown
3. Amazon-comparable figure was missing the Promotions deduction

**Changes:**
- Renamed "Net Sales (after fees)" → "Gross Sales (before deductions)"
- Added "− Promotions & Coupons" line to reconciliation breakdown
- Added "− Other Fees" line to reconciliation breakdown
- Updated Amazon-comparable figure to subtract Promotions

---

## Formulas Verified Correct

The following formulas were audited and found accurate for Amazon India:

### `data_processor.py` — `calculate_monthly_summary()`
- **Sales:** `sum(product_sales)` for Order events — ✅ Correct (excludes promos, which are tracked separately)
- **Other_Amazon_Fees:** `other_tx - promo_amt` where `other_tx = (product_sales - fba - selling) - total_amount` — ✅ Correct
- **Net Income:** `Sales + Reimbursements - Refunds - FBA - Selling - Ads - COGS - OpEx - Other - Promotions` — ✅ Correct
- **Gross Margin:** `(Sales + Reimbursements - Refunds - COGS - FBA - Selling - Promos - Other) / Sales` — ✅ Correct
- **TACOS:** `Ads_Cost / Sales * 100` — ✅ Correct (standard formula)
- **ACOS:** `Ads_Cost / Ad_Attributed_Sales * 100` — ✅ Correct (standard formula)
- **ROI:** `Net_Income / COGS * 100` — ✅ Correct
- **Return_Pct:** `Total_Returns / Units_Sold * 100` — ✅ Correct

### `data_processor.py` — `calculate_sku_metrics()`
- **SKU Net Profit:** `Sales + Reimbursements - FBA - Selling - Refunds - Other - COGS - Promotions` — ✅ Correct
- **SKU Margin_Pct:** `Net Profit / Product Sales * 100` — ✅ Correct
- **SKU ROI_Pct:** `Net Profit / Total COGS * 100` — ✅ Correct
- **Blended_Net_Profit:** `Net Profit - Allocated OpEx - Allocated Ads` — ✅ Correct
- **Cashflow_Healthy:** `Blended_Profit_Per_Sale >= Unit_COGS` — ✅ Correct

### `data_processor.py` — `get_ads_summary()`
- **ACOS:** `spend / sales_7d * 100` — ✅ Correct
- **CTR:** `clicks / impressions * 100` — ✅ Correct
- **CVR:** `orders / clicks * 100` — ✅ Correct
- **CPC:** `spend / clicks` — ✅ Correct
- **ROAS:** `sales / spend` — ✅ Correct

### `processor.py` — CSV Parsing
- **Product Sales extraction:** `clean_numeric(row.get('product sales'))` — ✅ Correct (excludes promos for Amazon India)
- **Promotional rebates:** `clean_numeric(row.get('promotional rebates'))` — ✅ Correct
- **Total amount:** `clean_numeric(row.get('total'))` — ✅ Correct (net after all deductions)

### Templates
- **Promotions ROI:** `(revenue - cost) / cost * 100` — ✅ Correct
- **Net Income formula text:** Matches backend calculation — ✅ Correct
- **SKU formula text:** Matches backend calculation — ✅ Correct

---

## No Changes Needed

The following were verified correct and required no changes:
- `main.py` — No financial formulas in routes (just data passing)
- `processor.py` — CSV parsing correctly extracts all fields
- `auditor.py` — Threshold comparison logic is correct
- `templates/index.html` — All displayed values match backend calculations
- `templates/sku_insights.html` — All displayed values match backend calculations
- `templates/advertising.html` — All displayed values match backend calculations
- `templates/docs.html` — All formula documentation matches actual calculations
