import streamlit as st
import pandas as pd
import numpy as np

# ─── PAGE CONFIG ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Inventory Demand Forecaster",
    page_icon="📦",
    layout="wide"
)

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
RETURN_PERIOD = 77   # April(30) + May(31) + June(16)
ADS_DAYS      = 10   # days of ads data in file
SAFETY_BUFFER = 1.10 # 10% safety stock on reorder qty

# ─── STYLING ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .zone-red    { background:#fff0ee; border:1px solid #e8957a; border-radius:8px; padding:10px; }
    .zone-orange { background:#fff8ee; border:1px solid #f0b86a; border-radius:8px; padding:10px; }
    .zone-green  { background:#eef8f2; border:1px solid #7ac89a; border-radius:8px; padding:10px; }
    .badge-red    { background:#d9442a; color:white; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:700; }
    .badge-orange { background:#e8910a; color:white; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:700; }
    .badge-green  { background:#2a8a4a; color:white; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:700; }
    .metric-box   { background:rgba(255,255,255,0.6); border-radius:6px; padding:8px 10px; margin:3px 0; }
    .metric-label { font-size:11px; color:#6b7280; margin-bottom:2px; }
    .metric-value { font-size:14px; font-weight:700; color:#111; }
    .reorder-value { font-size:20px; font-weight:800; color:#111; }
    .sku-code     { font-family:monospace; font-size:13px; font-weight:700; color:#111; }
    .color-sku    { font-size:11px; color:#6b7280; }
    .days-tag     { font-size:11px; font-weight:700; padding:3px 8px; border-radius:4px; display:inline-block; margin-top:4px; }
    .ret-badge    { font-size:11px; color:#059669; font-weight:600; }
    .ret-no       { font-size:11px; color:#9ca3af; }
    .section-title { font-size:13px; font-weight:700; color:#374151; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px; }
    div[data-testid="stHorizontalBlock"] { gap: 12px; }
</style>
""", unsafe_allow_html=True)

# ─── IMAGE HELPER (exact same logic as user's other Streamlit model) ──────────
def get_image_url(color_sku, img_df):
    """Match color SKU to image URL using same logic as user's other model."""
    if img_df is None or img_df.empty:
        return None

    img_row = img_df[
        img_df["Link slug"].astype(str).str.strip() == str(color_sku).strip()
    ]

    if img_row.empty:
        return None

    img_url = str(img_row.iloc[0]["Original URL"]).strip()

    # Dropbox FIX (same as user's other model)
    if "dropbox.com" in img_url:
        if "dl=1" in img_url:
            img_url = img_url.replace("dl=1", "raw=1")
        elif "dl=0" in img_url:
            img_url = img_url.replace("dl=0", "raw=1")
        elif "raw=1" not in img_url:
            img_url = img_url + "&raw=1"

    return img_url


def render_image(color_sku, img_df):
    """Render product image using st.markdown with unsafe_allow_html (same as user's other model)."""
    img_url = get_image_url(color_sku, img_df)
    if img_url:
        st.markdown(
            f'<img src="{img_url}" style="width:100%; border-radius:10px; object-fit:cover;">',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div style="width:100%;height:140px;background:#f3f4f6;border-radius:10px;'
            'display:flex;align-items:center;justify-content:center;color:#9ca3af;font-size:13px;">No image</div>',
            unsafe_allow_html=True
        )

# ─── FILE PARSERS ─────────────────────────────────────────────────────────────

@st.cache_data
def parse_inventory(file_bytes):
    df = pd.read_excel(file_bytes)
    df.columns = df.columns.str.strip()
    # Flexible column detection
    col_map = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "").replace("_", "")
        if "itemskucode" in cl or ("itemsku" in cl and "code" in cl):
            col_map["item_sku"] = col
        elif "colorsku" in cl and "item" not in cl:
            col_map["color_sku"] = col
        elif "currentstock" in cl or "stockonhand" in cl:
            col_map["current_stock"] = col
        elif "colorlevelopenpo" in cl or ("openpo" in cl) or ("openpo" in cl):
            col_map["open_po"] = col
        elif "15days" in cl or "salesaverage" in cl or "avgdaily" in cl:
            col_map["avg_15d"] = col

    required = ["item_sku", "current_stock", "avg_15d"]
    missing = [r for r in required if r not in col_map]
    if missing:
        st.error(f"Inventory file missing columns for: {missing}")
        return None

    out = pd.DataFrame()
    out["item_sku"]       = df[col_map["item_sku"]].astype(str).str.strip()
    out["color_sku"]      = df[col_map["color_sku"]].astype(str).str.strip() if "color_sku" in col_map else ""
    out["current_stock"]  = pd.to_numeric(df[col_map["current_stock"]], errors="coerce").fillna(0).clip(lower=0).astype(int)
    out["open_po"]        = pd.to_numeric(df[col_map.get("open_po", col_map["current_stock"])], errors="coerce").fillna(0).clip(lower=0).astype(int) if "open_po" in col_map else 0
    out["avg_15d"]        = pd.to_numeric(df[col_map["avg_15d"]], errors="coerce").fillna(0).round(2)
    out["net_stock"]      = out["current_stock"] + out["open_po"]

    out = out[out["item_sku"].notna() & (out["item_sku"] != "nan")]
    out = out[out["avg_15d"] > 0.05]
    return out.reset_index(drop=True)


@st.cache_data
def parse_returns(file_bytes):
    """Parse multi-sheet returns file (Amazon, Flipkart, Myntra) with April/May/June columns."""
    xl = pd.ExcelFile(file_bytes)
    ret = {}
    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        df.columns = df.columns.str.strip()
        # Find item SKU column
        sku_col = next((c for c in df.columns if "item sku" in c.lower() or "itemsku" in c.lower().replace(" ","")), None)
        if sku_col is None:
            continue
        # Find month columns (any numeric column that isn't the SKU)
        month_cols = [c for c in df.columns if c != sku_col and pd.api.types.is_numeric_dtype(df[c])]
        # Also try April/May/June by name
        named_months = [c for c in df.columns if c.lower() in ["april","may","june","jan","feb","mar","jul","aug","sep","oct","nov","dec"]]
        use_cols = named_months if named_months else month_cols

        for _, row in df.iterrows():
            sku = str(row[sku_col]).strip()
            if not sku or sku == "nan":
                continue
            total = sum(max(0, pd.to_numeric(row.get(c, 0), errors="coerce") or 0) for c in use_cols)
            if total > 0:
                ret[sku] = ret.get(sku, 0) + total

    return ret  # { item_sku: total_return_qty }


@st.cache_data
def parse_ads(file_bytes):
    """Parse ads file: row 0 = dates, row 1 = ADS SPEND/ADS UNIT, row 2+ = data by Color SKU."""
    raw = pd.read_excel(file_bytes, header=None)
    if len(raw) < 3:
        return {}

    # Find date pairs (every 2 cols from col 2)
    pairs = []
    for c in range(2, len(raw.columns), 2):
        if pd.notna(raw.iloc[0, c]):
            pairs.append((c, c + 1 if c + 1 < len(raw.columns) else c))

    ads = {}
    for _, row in raw.iloc[2:].iterrows():
        sku = str(row.iloc[0]).strip()
        if not sku or sku == "nan":
            continue
        total_spend = sum(max(0, pd.to_numeric(row.iloc[cs], errors="coerce") or 0) for cs, _ in pairs)
        total_units = sum(max(0, pd.to_numeric(row.iloc[cu], errors="coerce") or 0) for _, cu in pairs)
        if total_spend > 0 or total_units > 0:
            ads[sku] = {"spend": round(total_spend, 2), "units": int(total_units)}

    return ads  # { color_sku: {spend, units} }


@st.cache_data
def parse_images(file_bytes):
    """Parse images file: Link slug = Color SKU, Original URL = Dropbox image."""
    df = pd.read_excel(file_bytes)
    df.columns = df.columns.str.strip()
    # Keep only Link slug and Original URL
    slug_col = next((c for c in df.columns if "link slug" in c.lower() or "linkslug" in c.lower()), None)
    url_col  = next((c for c in df.columns if "original url" in c.lower() or "originalurl" in c.lower()), None)
    if slug_col is None or url_col is None:
        st.error("Image file must have 'Link slug' and 'Original URL' columns.")
        return None
    out = df[[slug_col, url_col]].copy()
    out.columns = ["Link slug", "Original URL"]
    out = out.dropna(subset=["Link slug", "Original URL"])
    out["Link slug"] = out["Link slug"].astype(str).str.strip()
    out["Original URL"] = out["Original URL"].astype(str).str.strip()
    return out


# ─── DEMAND COMPUTATION ───────────────────────────────────────────────────────

def compute_demand(inv_df, ret_data, ads_data, ads_dir, ads_pct, festival):
    """
    Adj demand/day = base_avg × (1 − return_rate) × ads_multiplier × festival_mult
    45-day demand  = adj_demand/day × 45
    Reorder qty    = max(0, 45d_demand − net_stock) × 1.10
    """
    ads_mult  = (1 + ads_pct) if ads_dir == "increase" else (1 - ads_pct)
    fest_mult = 1.25 if festival else 1.0

    # Count item SKUs per color SKU for distributing ads units
    color_count = inv_df["color_sku"].value_counts().to_dict()

    rows = []
    for _, r in inv_df.iterrows():
        item_sku  = r["item_sku"]
        color_sku = r["color_sku"]

        # ── Return rate from file (per SKU)
        ret_qty  = ret_data.get(item_sku, 0)
        est_sold = r["avg_15d"] * RETURN_PERIOD
        ret_rate = min(ret_qty / est_sold, 0.95) if est_sold > 0 else 0
        has_ret  = item_sku in ret_data

        # ── Ads lift from file (per color SKU, distributed across sibling SKUs)
        ad       = ads_data.get(color_sku, {"spend": 0, "units": 0})
        n_sibs   = color_count.get(color_sku, 1)
        ads_daily_units_per_item = ad["units"] / ADS_DAYS / n_sibs
        lift_factor = (ads_daily_units_per_item / r["avg_15d"]) if r["avg_15d"] > 0 else 0
        eff_ads_mult = ads_mult * (1 + min(lift_factor * 0.3, 0.5))

        # ── Combined multiplier and demand
        combined = (1 - ret_rate) * eff_ads_mult * fest_mult
        adj_day  = round(r["avg_15d"] * combined, 3)
        d45      = round(adj_day * 45, 1)
        gap      = max(0, d45 - r["net_stock"])
        reorder  = round(gap * SAFETY_BUFFER)
        days_left = round(r["net_stock"] / adj_day, 1) if adj_day > 0.01 else 999
        days_stk  = round(r["current_stock"] / adj_day, 1) if adj_day > 0.01 else 999
        coverage  = min(200, round(r["net_stock"] / d45 * 100)) if d45 > 0 else 100

        # ── Zone
        if days_left < 15 or days_stk < 10:
            zone = "red"
        elif days_left < 30:
            zone = "orange"
        else:
            zone = "green"

        rows.append({
            "item_sku":     item_sku,
            "color_sku":    color_sku,
            "current_stock":r["current_stock"],
            "open_po":      r["open_po"],
            "net_stock":    r["net_stock"],
            "avg_15d":      r["avg_15d"],
            "ret_rate":     round(ret_rate, 4),
            "ret_qty":      int(ret_qty),
            "has_ret":      has_ret,
            "ad_spend":     ad["spend"],
            "ad_units":     ad["units"],
            "adj_day":      adj_day,
            "d45":          d45,
            "reorder":      int(reorder),
            "days_left":    days_left,
            "days_stk":     days_stk,
            "coverage":     int(coverage),
            "zone":         zone,
        })

    result = pd.DataFrame(rows)
    return result.sort_values("reorder", ascending=False).reset_index(drop=True)


# ─── ZONE CARD RENDERER ───────────────────────────────────────────────────────

ZONE_COLORS = {
    "red":    {"bg": "#fff0ee", "border": "#e8957a", "text": "#7a2010", "dot": "#d9442a", "label": "🔴 Red",    "badge": "Critical"},
    "orange": {"bg": "#fff8ee", "border": "#f0b86a", "text": "#7a4a00", "dot": "#e8910a", "label": "🟠 Orange", "badge": "Watch"},
    "green":  {"bg": "#eef8f2", "border": "#7ac89a", "text": "#1a5c32", "dot": "#2a8a4a", "label": "🟢 Green",  "badge": "OK"},
}

def render_sku_card(row, img_df):
    z = ZONE_COLORS[row["zone"]]

    with st.container():
        st.markdown(
            f'<div style="background:{z["bg"]};border:1px solid {z["border"]};border-radius:10px;overflow:hidden;padding:0;margin-bottom:8px;">',
            unsafe_allow_html=True
        )

        # ── IMAGE BLOCK (first row — same logic as user's other model) ──────
        left_col, right_col = st.columns([1, 1])
        with left_col:
            color_sku = str(row["color_sku"]).strip()
            img_row = img_df[
                img_df["Link slug"].astype(str).str.strip() == color_sku
            ] if img_df is not None and not img_df.empty else pd.DataFrame()

            if not img_row.empty:
                img_url = str(img_row.iloc[0]["Original URL"]).strip()

                # Dropbox FIX (exact same as user's other model)
                if "dropbox.com" in img_url:
                    if "dl=1" in img_url:
                        img_url = img_url.replace("dl=1", "raw=1")
                    elif "dl=0" in img_url:
                        img_url = img_url.replace("dl=0", "raw=1")
                    elif "raw=1" not in img_url:
                        img_url = img_url + "&raw=1"

                st.markdown(
                    f'<img src="{img_url}" style="width:100%; border-radius:10px; object-fit:cover; max-height:160px;">',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    '<div style="width:100%;height:140px;background:rgba(0,0,0,0.05);border-radius:10px;'
                    'display:flex;align-items:center;justify-content:center;color:#9ca3af;font-size:13px;">🖼️ No image</div>',
                    unsafe_allow_html=True
                )

        # ── METRICS BLOCK ────────────────────────────────────────────────────
        with right_col:
            # Zone badge + SKU
            st.markdown(
                f'<span class="badge-{row["zone"]}">{z["badge"]}</span>',
                unsafe_allow_html=True
            )
            st.markdown(f'<div class="sku-code">{row["item_sku"]}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="color-sku">{row["color_sku"]}</div>', unsafe_allow_html=True)

            # Key metrics
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(
                    f'<div class="metric-box"><div class="metric-label">Stock</div>'
                    f'<div class="metric-value">{row["current_stock"]}</div></div>',
                    unsafe_allow_html=True
                )
                st.markdown(
                    f'<div class="metric-box"><div class="metric-label">Adj dmnd/day</div>'
                    f'<div class="metric-value">{row["adj_day"]:.2f}</div></div>',
                    unsafe_allow_html=True
                )
            with col2:
                st.markdown(
                    f'<div class="metric-box"><div class="metric-label">Open PO</div>'
                    f'<div class="metric-value">{row["open_po"] if row["open_po"] > 0 else "—"}</div></div>',
                    unsafe_allow_html=True
                )
                st.markdown(
                    f'<div class="metric-box"><div class="metric-label">45d demand</div>'
                    f'<div class="metric-value">{row["d45"]:.1f}</div></div>',
                    unsafe_allow_html=True
                )

            # Reorder qty — big and prominent
            st.markdown(
                f'<div class="metric-box" style="background:rgba(255,255,255,0.7);margin-top:4px;">'
                f'<div class="metric-label">Reorder qty</div>'
                f'<div class="reorder-value" style="color:{z["dot"]};">{row["reorder"]}</div></div>',
                unsafe_allow_html=True
            )

        # ── FOOTER: days left + return rate + coverage bar ───────────────────
        days_str = "∞" if row["days_left"] == 999 else f'{row["days_left"]}d'
        ret_str  = f'↩️ {row["ret_rate"]*100:.1f}% ✓' if row["has_ret"] else f'↩️ 0% (no file)'
        ret_color= "#059669" if row["has_ret"] else "#9ca3af"

        st.markdown(
            f'<div style="padding:6px 10px 8px 10px;">'
            f'<div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px;">'
            f'<span style="color:{z["text"]};font-weight:700;">{z["label"]} · {days_str} stock left</span>'
            f'<span style="color:{ret_color};font-weight:600;">{ret_str}</span>'
            f'</div>'
            f'<div style="height:5px;background:rgba(0,0,0,0.1);border-radius:3px;overflow:hidden;">'
            f'<div style="width:{min(row["coverage"],100)}%;height:100%;background:{z["dot"]};border-radius:3px;"></div>'
            f'</div>'
            f'<div style="font-size:10px;color:#6b7280;margin-top:2px;text-align:right;">'
            f'Net stock {row["net_stock"]} / 45d need {row["d45"]} = {row["coverage"]}% covered</div>'
            f'</div>',
            unsafe_allow_html=True
        )

        st.markdown('</div>', unsafe_allow_html=True)


# ─── MAIN APP ─────────────────────────────────────────────────────────────────

def main():
    st.title("📦 Inventory Demand Forecaster")
    st.caption("Upload your files — demand predicted from real return rates, ads data and stock levels")

    # ── SIDEBAR: FILE UPLOADERS ───────────────────────────────────────────────
    with st.sidebar:
        st.header("📂 Upload Report Files")
        st.caption("Auto-detected · Re-upload any file to refresh its data")

        inv_file = st.file_uploader(
            "📦 Inventory file",
            type=["xlsx", "xls", "csv"],
            help="Needs: Item SKU Code · Color SKU · Current Stock · Color Level Open PO · 15 days sales average",
            key="inv"
        )
        ret_file = st.file_uploader(
            "↩️ Returns file",
            type=["xlsx", "xls", "csv"],
            help="Multi-sheet (Amazon/Flipkart/Myntra) with Item SKU Code + April/May/June columns",
            key="ret"
        )
        ads_file = st.file_uploader(
            "📣 Ads file",
            type=["xlsx", "xls", "csv"],
            help="Row 0 = dates, Row 1 = ADS SPEND/ADS UNIT, Row 2+ = data by Color SKU",
            key="ads"
        )
        img_file = st.file_uploader(
            "🖼️ Images file",
            type=["xlsx", "xls", "csv"],
            help="Link slug (Color SKU) + Original URL (Dropbox raw link)",
            key="img"
        )

        st.divider()

        # ── DEMAND CONTROLS ───────────────────────────────────────────────────
        st.header("⚙️ Demand Controls")

        ads_dir = st.radio(
            "📣 Ads impact direction",
            options=["increase", "decrease"],
            format_func=lambda x: "📈 Increasing demand" if x == "increase" else "📉 Decreasing demand",
            horizontal=True,
            key="ads_dir"
        )

        ads_pct = st.select_slider(
            "Ads impact %",
            options=[0, 5, 10, 15, 20, 30, 40, 50, 75, 100],
            value=10,
            format_func=lambda x: f"{x}%" if x > 0 else "0% — baseline",
            key="ads_pct"
        ) / 100.0

        festival = st.radio(
            "🎉 Festival / offer in next 45 days?",
            options=["No", "Yes"],
            horizontal=True,
            key="festival"
        ) == "Yes"

        if festival:
            st.info("Festival adds ×1.25 uplift on top of ads adjustment")

        st.divider()
        st.markdown(
            "**Formula:**\n\n"
            "`Adj day = base × (1−return) × ads_mult × festival`\n\n"
            "`45d = adj_day × 45`\n\n"
            "`Reorder = max(0, 45d − net_stock) × 1.10`\n\n"
            "`net_stock = current_stock + open_PO`"
        )

    # ── PARSE FILES ───────────────────────────────────────────────────────────
    if inv_file is None:
        st.info("👈 Upload your **Inventory file** from the sidebar to begin. Then optionally add Returns, Ads, and Images files.")
        return

    with st.spinner("Parsing files…"):
        inv_df   = parse_inventory(inv_file.read())
        ret_data = parse_returns(ret_file.read()) if ret_file else {}
        ads_data = parse_ads(ads_file.read())     if ads_file else {}
        img_df   = parse_images(img_file.read())  if img_file else None

    if inv_df is None or inv_df.empty:
        st.error("Could not parse inventory file. Check column names.")
        return

    # ── COMPUTE DEMAND ────────────────────────────────────────────────────────
    result = compute_demand(inv_df, ret_data, ads_data, ads_dir, ads_pct, festival)

    # ── DATA COVERAGE PILLS ───────────────────────────────────────────────────
    ret_cov = round(result["has_ret"].sum() / len(result) * 100) if len(result) else 0
    img_cov = 0
    if img_df is not None and not img_df.empty:
        img_slugs = set(img_df["Link slug"].astype(str).str.strip())
        img_cov   = round(result["color_sku"].isin(img_slugs).sum() / len(result) * 100)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📦 Active SKUs",     len(result))
    c2.metric("↩️ Return coverage", f"{ret_cov}%", help="SKUs with return rate from file")
    c3.metric("🖼️ Image coverage",  f"{img_cov}%", help="SKUs with product image")
    c4.metric("📣 Ads coverage",    f"{round(result['ad_spend'].gt(0).sum()/len(result)*100)}%", help="SKUs with ad spend data")

    st.divider()

    # ── KPI ZONE SUMMARY ─────────────────────────────────────────────────────
    red_df    = result[result["zone"] == "red"]
    orange_df = result[result["zone"] == "orange"]
    green_df  = result[result["zone"] == "green"]
    total_reorder = result["reorder"].sum()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("🔴 Red zone",    len(red_df),    delta="Reorder now",  delta_color="off")
    k2.metric("🟠 Orange zone", len(orange_df), delta="Reorder soon", delta_color="off")
    k3.metric("🟢 Green zone",  len(green_df),  delta="Sufficient",   delta_color="off")
    k4.metric("Total reorder units", f"{total_reorder:,}", help="Red + Orange combined")
    k5.metric("Combined multiplier",
              f"{(1 - 0.08) * (1 + ads_pct if ads_dir == 'increase' else 1 - ads_pct) * (1.25 if festival else 1.0):.3f}×",
              help="(1−return) × ads_mult × festival")

    st.divider()

    # ── TABS ─────────────────────────────────────────────────────────────────
    tab_cards, tab_table, tab_top50 = st.tabs(["🖼️ Zone cards", "📋 Full SKU table", "🏆 Top 50 reorder"])

    # ── FILTER ROW ────────────────────────────────────────────────────────────
    with tab_cards:
        fc1, fc2, fc3 = st.columns([2, 1, 1])
        with fc1:
            search_q = st.text_input("🔍 Search SKU", placeholder="Type item or color SKU…", key="card_search")
        with fc2:
            zone_filter = st.selectbox("Zone", ["All", "🔴 Red", "🟠 Orange", "🟢 Green"], key="card_zone")
        with fc3:
            sort_by = st.selectbox("Sort by", ["Reorder qty ↓", "Days left ↑", "SKU code"], key="card_sort")

        # Apply filters
        display = result.copy()
        if search_q:
            display = display[
                display["item_sku"].str.contains(search_q, case=False, na=False) |
                display["color_sku"].str.contains(search_q, case=False, na=False)
            ]
        if zone_filter != "All":
            z_map = {"🔴 Red": "red", "🟠 Orange": "orange", "🟢 Green": "green"}
            display = display[display["zone"] == z_map[zone_filter]]
        if sort_by == "Days left ↑":
            display = display.sort_values("days_left")
        elif sort_by == "SKU code":
            display = display.sort_values("item_sku")
        # else: already sorted by reorder qty

        st.caption(f"Showing {len(display)} SKUs")

        # Paginate cards
        CARDS_PER_PAGE = 12
        total_pages = max(1, (len(display) - 1) // CARDS_PER_PAGE + 1)
        page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="card_page") - 1
        page_data = display.iloc[page * CARDS_PER_PAGE: (page + 1) * CARDS_PER_PAGE]

        st.caption(f"Page {page + 1} of {total_pages}")

        # Render cards in 3-column grid
        COLS = 3
        for row_start in range(0, len(page_data), COLS):
            cols = st.columns(COLS)
            for ci, (_, row) in enumerate(page_data.iloc[row_start:row_start + COLS].iterrows()):
                with cols[ci]:
                    render_sku_card(row, img_df)

    # ── FULL TABLE ────────────────────────────────────────────────────────────
    with tab_table:
        ft1, ft2 = st.columns([2, 1])
        with ft1:
            tbl_search = st.text_input("🔍 Search", key="tbl_search")
        with ft2:
            tbl_zone = st.selectbox("Zone", ["All", "🔴 Red", "🟠 Orange", "🟢 Green"], key="tbl_zone")

        tbl_data = result.copy()
        if tbl_search:
            tbl_data = tbl_data[
                tbl_data["item_sku"].str.contains(tbl_search, case=False, na=False) |
                tbl_data["color_sku"].str.contains(tbl_search, case=False, na=False)
            ]
        if tbl_zone != "All":
            z_map = {"🔴 Red": "red", "🟠 Orange": "orange", "🟢 Green": "green"}
            tbl_data = tbl_data[tbl_data["zone"] == z_map[tbl_zone]]

        # Format for display
        display_tbl = tbl_data[[
            "item_sku", "color_sku", "zone", "current_stock", "open_po", "net_stock",
            "avg_15d", "ret_rate", "adj_day", "d45", "days_left", "reorder", "coverage"
        ]].copy()
        display_tbl["zone"]      = display_tbl["zone"].map({"red":"🔴 Red","orange":"🟠 Orange","green":"🟢 Green"})
        display_tbl["ret_rate"]  = (display_tbl["ret_rate"] * 100).round(1).astype(str) + "%"
        display_tbl["coverage"]  = display_tbl["coverage"].astype(str) + "%"
        display_tbl["days_left"] = display_tbl["days_left"].apply(lambda x: "∞" if x == 999 else str(x))
        display_tbl.columns      = ["Item SKU", "Color SKU", "Zone", "Stock", "Open PO", "Net stock",
                                     "Avg/day", "Return rate", "Adj dmnd/day", "45d demand", "Days left", "Reorder qty", "Coverage"]

        st.caption(f"{len(display_tbl)} SKUs")
        st.dataframe(display_tbl, use_container_width=True, hide_index=True)

        # Download button
        csv = tbl_data.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download as CSV", csv, "inventory_forecast.csv", "text/csv")

    # ── TOP 50 ────────────────────────────────────────────────────────────────
    with tab_top50:
        st.caption("Top 50 SKUs by reorder quantity — updates live with your control settings")
        top50 = result.head(50).copy()

        # Show with images inline
        for rank, (_, row) in enumerate(top50.iterrows(), 1):
            z    = ZONE_COLORS[row["zone"]]
            icol, rank_col, sku_col, metrics_col = st.columns([1, 0.3, 2, 3])

            # Image (same logic as render_sku_card)
            with icol:
                color_sku = str(row["color_sku"]).strip()
                img_row_match = img_df[
                    img_df["Link slug"].astype(str).str.strip() == color_sku
                ] if img_df is not None and not img_df.empty else pd.DataFrame()

                if not img_row_match.empty:
                    img_url = str(img_row_match.iloc[0]["Original URL"]).strip()
                    if "dropbox.com" in img_url:
                        if "dl=1" in img_url:
                            img_url = img_url.replace("dl=1", "raw=1")
                        elif "dl=0" in img_url:
                            img_url = img_url.replace("dl=0", "raw=1")
                        elif "raw=1" not in img_url:
                            img_url = img_url + "&raw=1"
                    st.markdown(
                        f'<img src="{img_url}" style="width:100%;border-radius:6px;object-fit:cover;max-height:60px;">',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown('<div style="height:60px;background:#f3f4f6;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:18px;">🖼️</div>', unsafe_allow_html=True)

            with rank_col:
                st.markdown(f"**#{rank}**")

            with sku_col:
                st.markdown(f'<div class="sku-code">{row["item_sku"]}</div>', unsafe_allow_html=True)
                st.markdown(f'<span class="badge-{row["zone"]}">{z["badge"]}</span>', unsafe_allow_html=True)
                ret_str = f'↩️ {row["ret_rate"]*100:.1f}% ✓' if row["has_ret"] else '↩️ no data'
                st.markdown(f'<div class="ret-badge">{ret_str}</div>' if row["has_ret"] else f'<div class="ret-no">{ret_str}</div>', unsafe_allow_html=True)

            with metrics_col:
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Stock",   row["current_stock"])
                m2.metric("Open PO", row["open_po"] or "—")
                m3.metric("Adj/day", f'{row["adj_day"]:.2f}')
                m4.metric("45d",     f'{row["d45"]:.0f}')
                m5.metric("**Reorder**", f'{row["reorder"]:,}')

            st.markdown("---")


if __name__ == "__main__":
    main()
