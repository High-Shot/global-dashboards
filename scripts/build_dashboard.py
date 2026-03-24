"""
NIC Industries — Dashboard Builder
Pulls data from Google Sheet tracker, outputs data.json and index.html.
Runs inside GitHub Actions on a weekly schedule.
"""

import json
import os
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

# ─── CONFIG ───────────────────────────────────────────────────────────────────

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

SHEET_ID = os.environ.get('GOOGLE_SHEET_ID', '')
CREDS_PATH = os.environ.get('GOOGLE_CREDENTIALS_PATH', '/tmp/credentials.json')

# Tabs to pull (order matters for display)
BRAND_TABS = [
    {'tab': 'CC_US', 'brand': 'Cerakote Ceramics', 'market': 'US', 'currency': '$'},
    {'tab': 'CC_CA', 'brand': 'Cerakote Ceramics', 'market': 'CA', 'currency': '$'},
    {'tab': 'CC_UK', 'brand': 'Cerakote Ceramics', 'market': 'UK', 'currency': '£'},
    {'tab': 'CC_FR', 'brand': 'Cerakote Ceramics', 'market': 'FR', 'currency': '€'},
    {'tab': 'CC_DE', 'brand': 'Cerakote Ceramics', 'market': 'DE', 'currency': '€'},
    {'tab': 'CC_IT', 'brand': 'Cerakote Ceramics', 'market': 'IT', 'currency': '€'},
    {'tab': 'CC_ES', 'brand': 'Cerakote Ceramics', 'market': 'ES', 'currency': '€'},
    {'tab': 'CC_NL', 'brand': 'Cerakote Ceramics', 'market': 'NL', 'currency': '€'},
    {'tab': 'CC_MX', 'brand': 'Cerakote Ceramics', 'market': 'MX', 'currency': '$'},
    {'tab': 'CL_US', 'brand': 'Cerakote Legacy', 'market': 'US', 'currency': '$'},
    {'tab': 'PP_US', 'brand': 'Prismatic Powders', 'market': 'US', 'currency': '$'},
]

# Account-level metric rows (1-indexed in the sheet, 0-indexed here for gspread)
ACCOUNT_ROWS = {
    'revenue': 4,       # row 5 in sheet = index 4
    'units': 5,
    'page_views': 6,
    'sessions': 7,
    'cvr': 8,
    'ad_spend': 9,
    'ad_sales': 10,
    'organic_sales': 11,
    'acos': 12,
    'tacos': 13,
    'roas': 14,
    'ntb_orders': 15,
    'ntb_sales': 16,
    'ntb_pct': 17,
}

# Product blocks: start row (0-indexed), 17-row stride
PRODUCT_BLOCK_START = 19  # row 20 = index 19
PRODUCT_BLOCK_SIZE = 17
PRODUCT_METRIC_OFFSETS = {
    'revenue': 1,
    'units': 2,
    'page_views': 3,
    'sessions': 4,
    'cvr': 5,
    'ad_spend': 6,
    'ad_sales': 7,
    'organic_sales': 8,
    'acos': 9,
    'tacos': 10,
    'roas': 11,
    'ntb_orders': 12,
    'ntb_sales': 13,
    'ntb_pct': 14,
    'bsr': 15,
}

PRODUCTS = [
    'Headlight Kit', 'Trim Coat', 'Paint Sealant', 'Tire Coat',
    'Plastic Restorer', 'Pro Ceramic Coating', 'Microfiber Towels',
    'Interior Detailer', 'Glass Coat', 'Vehicle Shampoo', 'Wheel Sealant',
]


# ─── GOOGLE SHEETS CLIENT ────────────────────────────────────────────────────

def get_sheet_client():
    if not SHEET_ID:
        print('ERROR: GOOGLE_SHEET_ID not set')
        sys.exit(1)

    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


# ─── DATA EXTRACTION ─────────────────────────────────────────────────────────

def safe_float(val):
    """Parse a cell value to float, handling currency symbols, commas, %."""
    if val is None or val == '' or val == '—':
        return None
    s = str(val).replace('$', '').replace('£', '').replace('€', '').replace(',', '').replace('%', '').replace('PLN', '').strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def extract_we_dates(header_row):
    """Pull WE date labels from header row (row 2)."""
    dates = []
    for cell in header_row[1:]:  # skip column A
        s = str(cell).strip()
        if s.startswith('WE '):
            dates.append(s)
        elif s:
            dates.append(s)
        else:
            break  # stop at first empty column
    return dates


def extract_metric_series(all_data, row_index, num_weeks):
    """Extract a list of numeric values from a row across WE columns."""
    if row_index >= len(all_data):
        return [None] * num_weeks
    row = all_data[row_index]
    values = []
    for col in range(1, num_weeks + 1):  # columns B onward (index 1+)
        val = row[col] if col < len(row) else None
        values.append(safe_float(val))
    return values


def extract_tab_data(spreadsheet, tab_config):
    """Extract all account-level and product-level data from a tab."""
    tab_name = tab_config['tab']

    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f'  Tab not found: {tab_name} — skipping')
        return None

    all_data = worksheet.get_all_values()
    if len(all_data) < 3:
        return None

    we_dates = extract_we_dates(all_data[1])  # row 2 (index 1)
    num_weeks = len(we_dates)

    # Account-level metrics
    account = {}
    for metric, row_idx in ACCOUNT_ROWS.items():
        account[metric] = extract_metric_series(all_data, row_idx, num_weeks)

    # Product-level metrics
    products = {}
    for i, product_name in enumerate(PRODUCTS):
        block_start = PRODUCT_BLOCK_START + (i * PRODUCT_BLOCK_SIZE)
        product_data = {}
        for metric, offset in PRODUCT_METRIC_OFFSETS.items():
            product_data[metric] = extract_metric_series(all_data, block_start + offset, num_weeks)
        products[product_name] = product_data

    return {
        'tab': tab_name,
        'brand': tab_config['brand'],
        'market': tab_config['market'],
        'currency': tab_config['currency'],
        'we_dates': we_dates,
        'account': account,
        'products': products,
    }


def find_latest_week_with_data(tab_data_list):
    """Find the most recent WE index that has actual revenue data."""
    for tab_data in tab_data_list:
        if tab_data is None:
            continue
        revenue = tab_data['account']['revenue']
        for i in range(len(revenue) - 1, -1, -1):
            if revenue[i] is not None and revenue[i] > 0:
                return i
    return 0


def build_global_summary(tab_data_list, latest_idx, prev_idx):
    """Aggregate global metrics across all tabs."""
    totals = {
        'revenue': 0, 'units': 0, 'ad_spend': 0, 'ad_sales': 0,
        'ntb_orders': 0, 'ntb_sales': 0, 'sessions': 0, 'page_views': 0,
    }
    prev_totals = {k: 0 for k in totals}

    for td in tab_data_list:
        if td is None:
            continue
        for metric in totals:
            val = td['account'][metric][latest_idx] if latest_idx < len(td['account'][metric]) else None
            if val:
                totals[metric] += val
            if prev_idx is not None and prev_idx >= 0:
                pval = td['account'][metric][prev_idx] if prev_idx < len(td['account'][metric]) else None
                if pval:
                    prev_totals[metric] += pval

    # Derived
    totals['organic_sales'] = totals['revenue'] - totals['ad_sales']
    totals['tacos'] = (totals['ad_spend'] / totals['revenue'] * 100) if totals['revenue'] > 0 else 0
    totals['acos'] = (totals['ad_spend'] / totals['ad_sales'] * 100) if totals['ad_sales'] > 0 else 0
    totals['roas'] = (totals['ad_sales'] / totals['ad_spend']) if totals['ad_spend'] > 0 else 0
    totals['cvr'] = (totals['units'] / totals['sessions'] * 100) if totals['sessions'] > 0 else 0

    # WoW changes
    wow = {}
    if prev_idx is not None and prev_totals['revenue'] > 0:
        wow['revenue'] = ((totals['revenue'] - prev_totals['revenue']) / prev_totals['revenue']) * 100
        wow['ad_spend'] = ((totals['ad_spend'] - prev_totals['ad_spend']) / prev_totals['ad_spend']) * 100 if prev_totals['ad_spend'] > 0 else 0
        wow['units'] = ((totals['units'] - prev_totals['units']) / prev_totals['units']) * 100 if prev_totals['units'] > 0 else 0

    return {'current': totals, 'wow': wow}


# ─── BUILD DATA.JSON ──────────────────────────────────────────────────────────

def build_data_json(spreadsheet):
    """Pull all data from the Google Sheet and return a JSON-serializable dict."""
    print('Extracting data from Google Sheet...')

    tab_data_list = []
    for config in BRAND_TABS:
        print(f'  Processing {config["tab"]}...')
        data = extract_tab_data(spreadsheet, config)
        tab_data_list.append(data)

    # Find latest week with data
    latest_idx = find_latest_week_with_data(tab_data_list)
    prev_idx = latest_idx - 1 if latest_idx > 0 else None

    # Get WE date labels from first valid tab
    we_dates = []
    for td in tab_data_list:
        if td and td['we_dates']:
            we_dates = td['we_dates']
            break

    latest_we = we_dates[latest_idx] if latest_idx < len(we_dates) else 'Unknown'

    # Global summary
    global_summary = build_global_summary(tab_data_list, latest_idx, prev_idx)

    # Brand snapshots (latest week only)
    brand_snapshots = []
    for td in tab_data_list:
        if td is None:
            continue
        acct = td['account']
        snap = {
            'tab': td['tab'],
            'brand': td['brand'],
            'market': td['market'],
            'currency': td['currency'],
            'revenue': acct['revenue'][latest_idx] if latest_idx < len(acct['revenue']) else None,
            'units': acct['units'][latest_idx] if latest_idx < len(acct['units']) else None,
            'ad_spend': acct['ad_spend'][latest_idx] if latest_idx < len(acct['ad_spend']) else None,
            'ad_sales': acct['ad_sales'][latest_idx] if latest_idx < len(acct['ad_sales']) else None,
            'tacos': acct['tacos'][latest_idx] if latest_idx < len(acct['tacos']) else None,
            'acos': acct['acos'][latest_idx] if latest_idx < len(acct['acos']) else None,
            'roas': acct['roas'][latest_idx] if latest_idx < len(acct['roas']) else None,
            'cvr': acct['cvr'][latest_idx] if latest_idx < len(acct['cvr']) else None,
            'ntb_orders': acct['ntb_orders'][latest_idx] if latest_idx < len(acct['ntb_orders']) else None,
            'ntb_pct': acct['ntb_pct'][latest_idx] if latest_idx < len(acct['ntb_pct']) else None,
        }

        # Product breakdown for this tab
        snap['products'] = {}
        for pname, pdata in td['products'].items():
            snap['products'][pname] = {
                'revenue': pdata['revenue'][latest_idx] if latest_idx < len(pdata['revenue']) else None,
                'units': pdata['units'][latest_idx] if latest_idx < len(pdata['units']) else None,
                'cvr': pdata['cvr'][latest_idx] if latest_idx < len(pdata['cvr']) else None,
                'tacos': pdata['tacos'][latest_idx] if latest_idx < len(pdata['tacos']) else None,
                'acos': pdata['acos'][latest_idx] if latest_idx < len(pdata['acos']) else None,
                'bsr': pdata['bsr'][latest_idx] if latest_idx < len(pdata['bsr']) else None,
            }

        brand_snapshots.append(snap)

    # Trend data (last 12 weeks for charts)
    trend_start = max(0, latest_idx - 11)
    trend_dates = we_dates[trend_start:latest_idx + 1]

    trend_data = {}
    for td in tab_data_list:
        if td is None:
            continue
        trend_data[td['tab']] = {
            'revenue': td['account']['revenue'][trend_start:latest_idx + 1],
            'ad_spend': td['account']['ad_spend'][trend_start:latest_idx + 1],
            'tacos': td['account']['tacos'][trend_start:latest_idx + 1],
            'units': td['account']['units'][trend_start:latest_idx + 1],
        }

    return {
        'generated_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
        'latest_we': latest_we,
        'we_dates': we_dates,
        'trend_dates': trend_dates,
        'global_summary': global_summary,
        'brand_snapshots': brand_snapshots,
        'trend_data': trend_data,
    }


# ─── HTML GENERATION ──────────────────────────────────────────────────────────

def generate_html(data):
    """Generate the full index.html dashboard from the data dict."""
    return HTML_TEMPLATE.replace('/*__DATA__*/', json.dumps(data, indent=2))


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    spreadsheet = get_sheet_client()
    data = build_data_json(spreadsheet)

    repo_root = Path(__file__).parent.parent
    data_path = repo_root / 'data.json'
    html_path = repo_root / 'index.html'

    # Write data.json
    with open(data_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f'Wrote {data_path}')

    # Write index.html
    with open(html_path, 'w') as f:
        f.write(generate_html(data))
    print(f'Wrote {html_path}')

    print('Done.')


# ─── HTML TEMPLATE ────────────────────────────────────────────────────────────

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NIC Industries — Weekly Performance Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface-2: #232733;
    --border: #2e3344;
    --text: #e4e6ed;
    --text-muted: #8b8fa3;
    --accent: #4f8cff;
    --green: #34d399;
    --red: #f87171;
    --yellow: #fbbf24;
    --orange: #fb923c;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    padding: 24px;
    max-width: 1440px;
    margin: 0 auto;
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 32px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
  }

  header h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.5px; }
  header .meta { color: var(--text-muted); font-size: 13px; }

  /* KPI Cards */
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
  }

  .kpi-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }

  .kpi-card .label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .kpi-card .value { font-size: 24px; font-weight: 700; letter-spacing: -0.5px; }
  .kpi-card .change { font-size: 12px; margin-top: 4px; }
  .kpi-card .change.up { color: var(--green); }
  .kpi-card .change.down { color: var(--red); }

  /* Section headers */
  .section-header {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 32px 0 16px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
  }

  /* Brand cards */
  .brand-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }

  .brand-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
  }

  .brand-card .brand-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }

  .brand-card .brand-name { font-size: 16px; font-weight: 600; }
  .brand-card .market-badge {
    background: var(--surface-2);
    color: var(--accent);
    font-size: 11px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 0.5px;
  }

  .brand-card .metrics-row {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 12px;
    margin-bottom: 8px;
  }

  .brand-card .metric { }
  .brand-card .metric .m-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; }
  .brand-card .metric .m-value { font-size: 16px; font-weight: 600; }

  .flag { display: inline-block; font-size: 10px; padding: 2px 6px; border-radius: 3px; font-weight: 600; }
  .flag.warn { background: rgba(251, 191, 36, 0.15); color: var(--yellow); }
  .flag.danger { background: rgba(248, 113, 113, 0.15); color: var(--red); }
  .flag.ok { background: rgba(52, 211, 153, 0.15); color: var(--green); }

  /* Product table */
  .product-table-wrapper {
    overflow-x: auto;
    margin-bottom: 32px;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  th {
    text-align: left;
    color: var(--text-muted);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }

  td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }

  tr:hover td { background: var(--surface-2); }
  td.product-name { font-weight: 500; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }

  /* Charts */
  .chart-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 32px;
  }

  .chart-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
  }

  .chart-card h3 { font-size: 13px; color: var(--text-muted); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }

  /* Action flags */
  .flags-list {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 32px;
  }

  .flag-item {
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .flag-item:last-child { border-bottom: none; }

  footer {
    text-align: center;
    color: var(--text-muted);
    font-size: 11px;
    margin-top: 48px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }

  @media (max-width: 768px) {
    .chart-grid { grid-template-columns: 1fr; }
    .brand-card .metrics-row { grid-template-columns: 1fr 1fr; }
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>

<header>
  <h1>NIC Industries — Weekly Performance</h1>
  <div class="meta">
    <span id="we-date"></span> &middot; <span id="gen-date"></span>
  </div>
</header>

<!-- Global KPIs -->
<div class="kpi-grid" id="kpi-grid"></div>

<!-- Trend Charts -->
<div class="section-header">12-Week Trends</div>
<div class="chart-grid">
  <div class="chart-card"><h3>Revenue</h3><canvas id="chart-revenue"></canvas></div>
  <div class="chart-card"><h3>TACoS</h3><canvas id="chart-tacos"></canvas></div>
</div>

<!-- Brand Snapshots -->
<div class="section-header">Brand &amp; Marketplace Snapshots</div>
<div class="brand-grid" id="brand-grid"></div>

<!-- Product Detail (CC_US) -->
<div class="section-header">Cerakote Ceramics US — Product Detail</div>
<div class="product-table-wrapper">
  <table id="product-table">
    <thead>
      <tr>
        <th>Product</th>
        <th class="num">Revenue</th>
        <th class="num">Units</th>
        <th class="num">CVR</th>
        <th class="num">TACoS</th>
        <th class="num">ACoS</th>
        <th class="num">BSR</th>
        <th>Health</th>
      </tr>
    </thead>
    <tbody id="product-tbody"></tbody>
  </table>
</div>

<!-- Action Flags -->
<div class="section-header">Action Flags</div>
<div class="flags-list" id="flags-list"></div>

<footer>
  Auto-generated from NIC Weekly Tracker &middot; Updated every Wednesday
</footer>

<script>
const DATA = /*__DATA__*/;

// ─── HELPERS ────────────────────────────────────────────────────────
function fmt(val, type, currency) {
  if (val === null || val === undefined) return '—';
  const c = currency || '$';
  switch(type) {
    case 'currency': return c + Number(val).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    case 'int': return Number(val).toLocaleString('en-US', {maximumFractionDigits: 0});
    case 'pct': return (Number(val) * 100).toFixed(1) + '%';
    case 'pct_raw': return Number(val).toFixed(1) + '%';
    case 'roas': return Number(val).toFixed(1) + 'x';
    case 'bsr': return val ? '#' + Number(val).toLocaleString('en-US', {maximumFractionDigits: 0}) : '—';
    default: return String(val);
  }
}

function wowBadge(val) {
  if (val === undefined || val === null) return '';
  const dir = val >= 0 ? 'up' : 'down';
  const arrow = val >= 0 ? '↑' : '↓';
  return `<span class="change ${dir}">${arrow} ${Math.abs(val).toFixed(1)}% WoW</span>`;
}

function healthFlag(acos, tacos, cvr) {
  const flags = [];
  if (acos !== null && acos > 0.30) flags.push('<span class="flag danger">ACoS &gt;30%</span>');
  else if (acos !== null && acos > 0.25) flags.push('<span class="flag warn">ACoS &gt;25%</span>');
  if (tacos !== null && tacos > 0.15) flags.push('<span class="flag danger">TACoS &gt;15%</span>');
  if (cvr !== null && cvr < 0.01 && cvr > 0) flags.push('<span class="flag warn">CVR &lt;1%</span>');
  if (flags.length === 0) flags.push('<span class="flag ok">OK</span>');
  return flags.join(' ');
}

// ─── RENDER KPIs ────────────────────────────────────────────────────
function renderKPIs() {
  const g = DATA.global_summary.current;
  const w = DATA.global_summary.wow;
  const grid = document.getElementById('kpi-grid');

  const kpis = [
    {label: 'Total Revenue', value: fmt(g.revenue, 'currency'), change: wowBadge(w.revenue)},
    {label: 'Total Units', value: fmt(g.units, 'int'), change: wowBadge(w.units)},
    {label: 'Ad Spend', value: fmt(g.ad_spend, 'currency'), change: wowBadge(w.ad_spend)},
    {label: 'Organic Sales', value: fmt(g.organic_sales, 'currency'), change: ''},
    {label: 'Blended TACoS', value: fmt(g.tacos, 'pct_raw'), change: ''},
    {label: 'Blended ACoS', value: fmt(g.acos, 'pct_raw'), change: ''},
    {label: 'Blended ROAS', value: fmt(g.roas, 'roas'), change: ''},
    {label: 'Blended CVR', value: fmt(g.cvr, 'pct_raw'), change: ''},
  ];

  grid.innerHTML = kpis.map(k => `
    <div class="kpi-card">
      <div class="label">${k.label}</div>
      <div class="value">${k.value}</div>
      ${k.change}
    </div>
  `).join('');
}

// ─── RENDER BRAND CARDS ─────────────────────────────────────────────
function renderBrands() {
  const grid = document.getElementById('brand-grid');

  grid.innerHTML = DATA.brand_snapshots.map(b => {
    if (!b.revenue && b.revenue !== 0) return ''; // skip tabs with no data
    return `
    <div class="brand-card">
      <div class="brand-header">
        <span class="brand-name">${b.brand}</span>
        <span class="market-badge">${b.market}</span>
      </div>
      <div class="metrics-row">
        <div class="metric"><div class="m-label">Revenue</div><div class="m-value">${fmt(b.revenue, 'currency', b.currency)}</div></div>
        <div class="metric"><div class="m-label">Ad Spend</div><div class="m-value">${fmt(b.ad_spend, 'currency', b.currency)}</div></div>
        <div class="metric"><div class="m-label">TACoS</div><div class="m-value">${fmt(b.tacos, 'pct')}</div></div>
      </div>
      <div class="metrics-row">
        <div class="metric"><div class="m-label">ACoS</div><div class="m-value">${fmt(b.acos, 'pct')}</div></div>
        <div class="metric"><div class="m-label">ROAS</div><div class="m-value">${fmt(b.roas, 'roas')}</div></div>
        <div class="metric"><div class="m-label">NTB %</div><div class="m-value">${fmt(b.ntb_pct, 'pct')}</div></div>
      </div>
    </div>`;
  }).join('');
}

// ─── RENDER PRODUCT TABLE ───────────────────────────────────────────
function renderProducts() {
  const ccus = DATA.brand_snapshots.find(b => b.tab === 'CC_US');
  if (!ccus) return;

  const tbody = document.getElementById('product-tbody');
  tbody.innerHTML = Object.entries(ccus.products).map(([name, p]) => `
    <tr>
      <td class="product-name">${name}</td>
      <td class="num">${fmt(p.revenue, 'currency')}</td>
      <td class="num">${fmt(p.units, 'int')}</td>
      <td class="num">${fmt(p.cvr, 'pct')}</td>
      <td class="num">${fmt(p.tacos, 'pct')}</td>
      <td class="num">${fmt(p.acos, 'pct')}</td>
      <td class="num">${fmt(p.bsr, 'bsr')}</td>
      <td>${healthFlag(p.acos, p.tacos, p.cvr)}</td>
    </tr>
  `).join('');
}

// ─── RENDER CHARTS ──────────────────────────────────────────────────
function renderCharts() {
  const dates = DATA.trend_dates;
  const chartOpts = {
    responsive: true,
    plugins: { legend: { labels: { color: '#8b8fa3', font: { size: 11 } } } },
    scales: {
      x: { ticks: { color: '#8b8fa3', font: { size: 10 } }, grid: { color: '#2e3344' } },
      y: { ticks: { color: '#8b8fa3', font: { size: 10 } }, grid: { color: '#2e3344' } },
    },
  };

  // Revenue chart — stacked by main tabs
  const revDatasets = [];
  const colors = ['#4f8cff', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#fb923c', '#38bdf8', '#e879f9', '#84cc16', '#f472b6', '#22d3ee'];
  let ci = 0;
  for (const [tab, td] of Object.entries(DATA.trend_data)) {
    const hasData = td.revenue.some(v => v !== null && v > 0);
    if (!hasData) continue;
    revDatasets.push({
      label: tab,
      data: td.revenue.map(v => v || 0),
      borderColor: colors[ci % colors.length],
      backgroundColor: colors[ci % colors.length] + '22',
      borderWidth: 2,
      tension: 0.3,
      fill: false,
    });
    ci++;
  }

  new Chart(document.getElementById('chart-revenue'), {
    type: 'line',
    data: { labels: dates, datasets: revDatasets },
    options: { ...chartOpts, scales: { ...chartOpts.scales, y: { ...chartOpts.scales.y, ticks: { ...chartOpts.scales.y.ticks, callback: v => '$' + (v/1000).toFixed(0) + 'k' } } } },
  });

  // TACoS chart
  const tacosDatasets = [];
  ci = 0;
  for (const [tab, td] of Object.entries(DATA.trend_data)) {
    const hasData = td.tacos.some(v => v !== null && v > 0);
    if (!hasData) continue;
    tacosDatasets.push({
      label: tab,
      data: td.tacos.map(v => v !== null ? v * 100 : null),
      borderColor: colors[ci % colors.length],
      borderWidth: 2,
      tension: 0.3,
      fill: false,
    });
    ci++;
  }

  new Chart(document.getElementById('chart-tacos'), {
    type: 'line',
    data: { labels: dates, datasets: tacosDatasets },
    options: { ...chartOpts, scales: { ...chartOpts.scales, y: { ...chartOpts.scales.y, ticks: { ...chartOpts.scales.y.ticks, callback: v => v.toFixed(0) + '%' } } } },
  });
}

// ─── RENDER ACTION FLAGS ────────────────────────────────────────────
function renderFlags() {
  const flags = [];

  for (const b of DATA.brand_snapshots) {
    if (!b.revenue && b.revenue !== 0) continue;

    // Account-level flags
    if (b.acos !== null && b.acos > 0.30) flags.push({level: 'danger', msg: `${b.tab}: ACoS at ${(b.acos*100).toFixed(1)}% (target: <30%)`});
    if (b.tacos !== null && b.tacos > 0.15) flags.push({level: 'danger', msg: `${b.tab}: TACoS at ${(b.tacos*100).toFixed(1)}% (target: <15%)`});

    // Product-level flags
    for (const [pname, p] of Object.entries(b.products || {})) {
      if (p.acos !== null && p.acos > 0.30) flags.push({level: 'warn', msg: `${b.tab} → ${pname}: ACoS ${(p.acos*100).toFixed(1)}%`});
      if (p.cvr !== null && p.cvr > 0 && p.cvr < 0.01) flags.push({level: 'warn', msg: `${b.tab} → ${pname}: CVR below 1%`});
    }
  }

  if (flags.length === 0) flags.push({level: 'ok', msg: 'No action flags this week. All metrics within target ranges.'});

  document.getElementById('flags-list').innerHTML = flags.map(f =>
    `<div class="flag-item"><span class="flag ${f.level}">${f.level.toUpperCase()}</span> ${f.msg}</div>`
  ).join('');
}

// ─── INIT ───────────────────────────────────────────────────────────
document.getElementById('we-date').textContent = DATA.latest_we;
document.getElementById('gen-date').textContent = 'Updated ' + new Date(DATA.generated_at).toLocaleDateString();
renderKPIs();
renderBrands();
renderProducts();
renderCharts();
renderFlags();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
