"""
notebooks/olist_analysis.py
=============================
Complete business analytics for the Olist e-commerce platform.

Reads ALL paths from the project root .env file via load_dotenv().
No hardcoded paths — deploy to any machine by setting values in .env.

Run options
-----------
  # As a script (generates all charts to reports/charts/):
  python notebooks/olist_analysis.py

  # As a Jupyter notebook:
  jupytext --to notebook notebooks/olist_analysis.py
  jupyter lab notebooks/olist_analysis.ipynb

Environment variables (set in .env at project root)
-----------------------------------------------------
  DATA_DIR   Path to raw CSV folder (default: data/raw/ relative to project root)
"""

# %% [markdown]
# # Olist E-Commerce Analytics Platform
# ## End-to-End Business Intelligence Report
#
# **Dataset**: Brazilian E-Commerce by Olist (2016-2018)
# **Scope**: 99,441 orders | R$15.8M GMV | 96,096 customers | 3,095 sellers

# %%
import os
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ── Resolve project root and load .env ───────────────────────────────────────
# __file__ = olist_platform/notebooks/olist_analysis.py
# PROJECT_ROOT = olist_platform/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Paths — all relative to PROJECT_ROOT, overridable via .env ───────────────
DATA_DIR    = Path(os.getenv("DATA_DIR") or str(PROJECT_ROOT / "data" / "raw"))
REPORTS_DIR = PROJECT_ROOT / "reports" / "charts"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

print(f"Data directory : {DATA_DIR}")
print(f"Reports output : {REPORTS_DIR}")

# ── Chart styling ─────────────────────────────────────────────────────────────
plt.rcParams.update({
    'figure.facecolor': 'white',
    'axes.facecolor': '#F8F9FA',
    'axes.spines.top': False,
    'axes.spines.right': False,
    'font.family': 'DejaVu Sans',
    'font.size': 11,
})
PALETTE = ['#065A82', '#1C7293', '#4EAFD1', '#9FD7F0', '#D4EEF7']
sns.set_palette(PALETTE)


# %% [markdown]
# ## 1. Data Loading

# %%
def load_csv(filename: str, **kwargs) -> pd.DataFrame:
    """Load a CSV from DATA_DIR. Raises a clear error if file is missing."""
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"CSV not found: {path}\n"
            f"Ensure all Olist CSV files are placed in: {DATA_DIR}/"
        )
    return pd.read_csv(path, **kwargs)


print("Loading datasets...")
orders = load_csv('olist_orders_dataset.csv',
    parse_dates=['order_purchase_timestamp','order_approved_at',
                 'order_delivered_carrier_date','order_delivered_customer_date',
                 'order_estimated_delivery_date'])
order_items  = load_csv('olist_order_items_dataset.csv', parse_dates=['shipping_limit_date'])
customers    = load_csv('olist_customers_dataset.csv')
products     = load_csv('olist_products_dataset.csv')
sellers      = load_csv('olist_sellers_dataset.csv')
payments     = load_csv('olist_order_payments_dataset.csv')
reviews      = load_csv('olist_order_reviews_dataset.csv',
    parse_dates=['review_creation_date','review_answer_timestamp'])
cat_trans    = load_csv('product_category_name_translation.csv')
mql          = load_csv('olist_marketing_qualified_leads_dataset.csv', parse_dates=['first_contact_date'])
closed_deals = load_csv('olist_closed_deals_dataset.csv', parse_dates=['won_date'])
geo          = load_csv('olist_geolocation_dataset.csv')

products_en = products.merge(cat_trans, on='product_category_name', how='left')
print("✅ All datasets loaded successfully.")


# %% [markdown]
# ## 2. Derived Columns & Enrichment

# %%
orders['delivery_days'] = (
    orders['order_delivered_customer_date'] - orders['order_purchase_timestamp']
).dt.days
orders['is_late'] = (
    orders['order_delivered_customer_date'] > orders['order_estimated_delivery_date']
)
orders['month'] = orders['order_purchase_timestamp'].dt.to_period('M')

order_value = order_items.groupby('order_id').agg(
    total_value=('price','sum'), freight=('freight_value','sum'),
    item_count=('order_item_id','count')
).reset_index()
orders = orders.merge(order_value, on='order_id', how='left')
orders = orders.merge(reviews[['order_id','review_score']].drop_duplicates('order_id'), on='order_id', how='left')
orders = orders.merge(customers[['customer_id','customer_state','customer_city']], on='customer_id', how='left')


# %% [markdown]
# ## 3. Chart 1 — Monthly Revenue & Order Trends

# %%
monthly = (
    orders[orders['order_status'] == 'delivered']
    .groupby('month')
    .agg(revenue=('total_value','sum'), orders=('order_id','count'))
    .reset_index()
)
monthly['month_dt'] = monthly['month'].dt.to_timestamp()

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
fig.suptitle('Monthly Revenue & Order Volume — Olist 2016–2018',
             fontsize=14, fontweight='bold', y=0.98)

ax1.plot(monthly['month_dt'], monthly['revenue']/1e6,
         color='#065A82', linewidth=2, marker='o', markersize=4)
ax1.fill_between(monthly['month_dt'], monthly['revenue']/1e6, alpha=0.15, color='#065A82')
ax1.set_ylabel('Revenue (R$ Millions)')
ax1.set_title('Monthly GMV')
ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f'R${x:.1f}M'))
ax1.grid(axis='y', alpha=0.4)

ax2.bar(monthly['month_dt'], monthly['orders'], color='#1C7293', alpha=0.85, width=20)
ax2.set_ylabel('Orders')
ax2.set_title('Monthly Order Count')
ax2.grid(axis='y', alpha=0.4)

plt.tight_layout()
out = REPORTS_DIR / '01_revenue_trend.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart saved: {out}")
print(f"Peak month: {monthly.loc[monthly['revenue'].idxmax(), 'month']}")
print(f"Peak revenue: R${monthly['revenue'].max()/1e6:.2f}M")


# %% [markdown]
# ## 4. Chart 2 — Customer RFM Segmentation

# %%
SNAPSHOT_DATE = orders['order_purchase_timestamp'].max() + timedelta(days=1)
delivered = orders[orders['order_status'] == 'delivered']
rfm = delivered.groupby('customer_id').agg(
    recency=('order_purchase_timestamp', lambda x: (SNAPSHOT_DATE - x.max()).days),
    frequency=('order_id', 'count'),
    monetary=('total_value', 'sum')
).reset_index()

rfm['R'] = pd.qcut(rfm['recency'].rank(method='first'),   4, labels=[4,3,2,1]).astype(int)
rfm['F'] = pd.qcut(rfm['frequency'].rank(method='first'), 4, labels=[1,2,3,4]).astype(int)
rfm['M'] = pd.qcut(rfm['monetary'].rank(method='first'),  4, labels=[1,2,3,4]).astype(int)
rfm['rfm_score'] = rfm['R'] + rfm['F'] + rfm['M']

def rfm_label(row):
    if row['R'] >= 3 and row['F'] >= 3 and row['M'] >= 3: return 'Champion'
    if row['R'] >= 3 and row['F'] >= 2:                   return 'Loyal'
    if row['R'] <= 2 and row['F'] >= 2:                   return 'At Risk'
    if row['R'] == 1 and row['F'] == 1:                   return 'Hibernating'
    if row['frequency'] == 1:                              return 'New'
    return 'One-Time Buyer'

rfm['segment'] = rfm.apply(rfm_label, axis=1)
seg_counts = rfm['segment'].value_counts().reset_index()
seg_counts.columns = ['segment','count']

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle('Customer RFM Segmentation', fontsize=14, fontweight='bold')

colors = ['#065A82','#1C7293','#4EAFD1','#F4A261','#E94F37','#2EC4B6']
ax1.pie(seg_counts['count'], labels=seg_counts['segment'],
        autopct='%1.1f%%', colors=colors, startangle=90)
ax1.set_title('Segment Distribution')

seg_spend = rfm.groupby('segment')['monetary'].mean().sort_values(ascending=True)
ax2.barh(seg_spend.index, seg_spend.values, color='#1C7293')
ax2.set_title('Average Total Spend per Segment (R$)')
ax2.set_xlabel('Average Spend (R$)')
ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f'R${x:,.0f}'))

plt.tight_layout()
out = REPORTS_DIR / '02_rfm_segments.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart saved: {out}")
print(f"Champions: {(rfm['segment']=='Champion').sum():,}")
print(f"At Risk:   {(rfm['segment']=='At Risk').sum():,}")


# %% [markdown]
# ## 5. Chart 3 — Marketing Funnel

# %%
funnel = mql.merge(closed_deals[['mql_id','won_date','seller_id']], on='mql_id', how='left')
funnel['converted'] = funnel['seller_id'].notna()
ch_stats = funnel.groupby('origin').agg(
    leads=('mql_id','count'),
    converted=('converted','sum')
).reset_index()
ch_stats['conversion_rate'] = ch_stats['converted'] / ch_stats['leads'] * 100
ch_stats = ch_stats.sort_values('conversion_rate', ascending=True)

fig, ax = plt.subplots(figsize=(12, 6))
bars = ax.barh(ch_stats['origin'], ch_stats['conversion_rate'],
               color=['#E94F37' if v < 5 else '#1C7293' for v in ch_stats['conversion_rate']])
for bar, val in zip(bars, ch_stats['conversion_rate']):
    ax.text(bar.get_width()+0.1, bar.get_y()+bar.get_height()/2,
            f'{val:.1f}%', va='center', fontsize=10)
ax.set_title('Marketing Channel Conversion Rate (MQL → Deal)', fontweight='bold')
ax.set_xlabel('Conversion Rate (%)')
ax.axvline(ch_stats['conversion_rate'].mean(), color='orange',
           linestyle='--', alpha=0.8, label=f"Avg {ch_stats['conversion_rate'].mean():.1f}%")
ax.legend()
plt.tight_layout()
out = REPORTS_DIR / '03_marketing_funnel.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart saved: {out}")
print(f"Overall conversion: {funnel['converted'].mean()*100:.1f}%")


# %% [markdown]
# ## 6. Chart 4 — Category Performance

# %%
items_en = order_items.merge(products_en[['product_id','product_category_name_english']],
                              on='product_id', how='left')
items_en['cat'] = items_en['product_category_name_english'].fillna('unknown')
cat_rev = items_en.groupby('cat').agg(
    revenue=('price','sum'), orders=('order_id','nunique')).reset_index()
cat_rev = cat_rev.nlargest(12, 'revenue').sort_values('revenue', ascending=True)

fig, ax = plt.subplots(figsize=(12, 7))
ax.barh(cat_rev['cat'], cat_rev['revenue']/1e6, color='#065A82', alpha=0.85)
for i, (rev, n) in enumerate(zip(cat_rev['revenue'], cat_rev['orders'])):
    ax.text(rev/1e6+0.01, i, f'R${rev/1e6:.2f}M  ({n:,} orders)',
            va='center', fontsize=9)
ax.set_title('Top 12 Product Categories by Revenue', fontweight='bold')
ax.set_xlabel('Revenue (R$ Millions)')
plt.tight_layout()
out = REPORTS_DIR / '04_category_performance.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart saved: {out}")


# %% [markdown]
# ## 7. Chart 5 — Delivery Performance

# %%
delivered_orders = orders[orders['order_status']=='delivered'].dropna(subset=['delivery_days'])

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle('Delivery Performance Analysis', fontsize=14, fontweight='bold')

ax1.hist(delivered_orders['delivery_days'].clip(0, 60), bins=40,
         color='#1C7293', alpha=0.85, edgecolor='white')
ax1.axvline(delivered_orders['delivery_days'].median(), color='#E94F37',
            linestyle='--', linewidth=2, label=f"Median: {delivered_orders['delivery_days'].median():.0f} days")
ax1.set_title('Delivery Days Distribution')
ax1.set_xlabel('Days to Deliver')
ax1.set_ylabel('Orders')
ax1.legend()

state_late = delivered_orders.groupby('customer_state')['is_late'].mean().sort_values(ascending=False).head(10)
ax2.barh(state_late.index, state_late.values * 100,
         color=['#E94F37' if v > 0.1 else '#1C7293' for v in state_late.values])
ax2.set_title('Late Delivery Rate by State (Top 10)')
ax2.set_xlabel('Late Delivery Rate (%)')
plt.tight_layout()
out = REPORTS_DIR / '05_delivery_performance.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart saved: {out}")
on_time = (~delivered_orders['is_late']).mean() * 100
print(f"On-time delivery rate: {on_time:.1f}%")
print(f"Avg delivery days:     {delivered_orders['delivery_days'].mean():.1f}")


# %% [markdown]
# ## 8. Chart 6 — Seller Performance

# %%
seller_rev = order_items.groupby('seller_id').agg(
    revenue=('price','sum'), orders=('order_id','nunique')).reset_index()
seller_rev = seller_rev.sort_values('revenue', ascending=False).reset_index(drop=True)
seller_rev['cum_pct'] = seller_rev['revenue'].cumsum() / seller_rev['revenue'].sum() * 100
seller_rev['seller_pct'] = (seller_rev.index + 1) / len(seller_rev) * 100

top5_rev  = seller_rev[seller_rev['seller_pct'] <= 5]['revenue'].sum() / seller_rev['revenue'].sum() * 100
tier_bins = [0, 0.05, 0.20, 1.0]
tier_lbls = ['Top 5%', 'Mid 6-20%', 'Long Tail']
seller_rev['tier'] = pd.cut(seller_rev['seller_pct']/100, bins=tier_bins, labels=tier_lbls)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle('Seller Performance', fontsize=14, fontweight='bold')

ax1.plot(seller_rev['seller_pct'], seller_rev['cum_pct'], color='#065A82', linewidth=2)
ax1.plot([0,100],[0,100], 'k--', alpha=0.4, label='Perfect equality')
ax1.axvline(5, color='#E94F37', linestyle=':', alpha=0.8)
ax1.text(6, 35, f'Top 5%\n= {top5_rev:.0f}%\nof revenue', fontsize=9, color='#E94F37')
ax1.set_title('Seller Revenue Concentration (Lorenz Curve)')
ax1.set_xlabel('Seller Percentile')
ax1.set_ylabel('Cumulative Revenue %')
ax1.legend()

tier_data = seller_rev.groupby('tier')['revenue'].sum()
ax2.pie(tier_data, labels=tier_data.index, autopct='%1.1f%%',
        colors=['#065A82','#4EAFD1','#D4EEF7'])
ax2.set_title('Revenue Share by Seller Tier')

plt.tight_layout()
out = REPORTS_DIR / '06_seller_performance.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart saved: {out}")


# %% [markdown]
# ## 9. Chart 7 — Geographic Analysis

# %%
state_orders = orders.groupby('customer_state').agg(
    order_count=('order_id','count'),
    avg_value=('total_value','mean')
).reset_index().sort_values('order_count', ascending=False).head(15)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))
fig.patch.set_facecolor('white')
fig.suptitle('Geographic Demand Analysis', fontsize=14, fontweight='bold', color='#1F3864')

ax1.barh(state_orders['customer_state'][::-1], state_orders['order_count'][::-1],
         color=['#E94F37' if s=='SP' else '#2E75B6' for s in state_orders['customer_state'][::-1]])
ax1.set_title('Orders by State (Top 15)', color='#1F3864')
ax1.set_xlabel('Order Count', color='#64748B')
ax1.tick_params(colors='#4A5568', labelcolor='#4A5568')
for spine in ax1.spines.values():
    spine.set_edgecolor('#E2E8F0')

ax2.barh(state_orders['customer_state'][::-1], state_orders['avg_value'][::-1],
         color='#2E75B6', alpha=0.85)
ax2.set_title('Average Order Value by State (R$)', color='#1F3864')
ax2.set_xlabel('Avg Order Value (R$)', color='#64748B')
ax2.tick_params(colors='#4A5568', labelcolor='#4A5568')
for spine in ax2.spines.values():
    spine.set_edgecolor('#E2E8F0')
ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f'R${x:,.0f}'))

plt.tight_layout()
out = REPORTS_DIR / '07_geographic.png'
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print(f"Chart saved: {out}")


# %% [markdown]
# ## 10. Chart 8 — Payment Analysis

# %%
pay_type = payments.groupby('payment_type').agg(
    count=('order_id','count'), value=('payment_value','sum')).reset_index()
pay_type = pay_type.sort_values('count', ascending=False)

install_dist = payments[payments['payment_type']=='credit_card']['payment_installments'].value_counts().sort_index()

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle('Payment Behaviour Analysis', fontsize=14, fontweight='bold')

ax1.pie(pay_type['count'], labels=pay_type['payment_type'],
        autopct='%1.1f%%', colors=['#065A82','#1C7293','#4EAFD1','#9FD7F0'])
ax1.set_title('Payment Type Distribution')

ax2.bar(install_dist.index[:12], install_dist.values[:12], color='#1C7293', alpha=0.85)
ax2.set_title('Credit Card Installment Choices')
ax2.set_xlabel('Number of Installments')
ax2.set_ylabel('Orders')

plt.tight_layout()
out = REPORTS_DIR / '08_payments.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart saved: {out}")

# %% [markdown]
# ## 11. Business Summary

# %%
print("\n" + "="*60)
print("OLIST BUSINESS INTELLIGENCE SUMMARY")
print("="*60)
delivered = orders[orders['order_status']=='delivered']
print(f"Total GMV          : R${orders['total_value'].sum():>12,.2f}")
print(f"Total Orders       : {len(orders):>12,}")
print(f"Delivered Orders   : {len(delivered):>12,}")
print(f"Avg Order Value    : R${orders['total_value'].mean():>12,.2f}")
print(f"Avg Review Score   : {orders['review_score'].mean():>12.2f} / 5.0")
print(f"On-Time Delivery   : {(~delivered['is_late']).mean()*100:>11.1f}%")
print(f"Avg Delivery Days  : {delivered['delivery_days'].mean():>12.1f}")
mql_rate = len(closed_deals)/len(mql)*100
print(f"MQL Conversion     : {mql_rate:>11.1f}%")
print("="*60)
print(f"\n✅ All 8 charts saved to: {REPORTS_DIR}")
