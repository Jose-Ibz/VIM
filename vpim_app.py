import os, calendar
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st
import chardet

# ───────────────────────────────
# CONFIG
# ───────────────────────────────
HIST_DIR = "historico"
os.makedirs(HIST_DIR, exist_ok=True)

CAMP_FAM    = 11
CAMP_START  = (9, 16)   # 16-sep
CAMP_END    = (11, 22)  # 22-nov
COVER_MESES = 9         # campaña cubre 9 meses
PRICE_LIMIT = 1500      # límite pedido normal
EXCEP_FAMS  = {17, 18, 21}

st.title("VIM   VIAMAR INVENTORY MANAGEMENT")

upload = st.file_uploader("Sube tu inventario CSV", type=["csv"])
if not upload:
    st.stop()

try:
    # Leer CSV con codificación auto‑detectada
    raw = upload.read()
    enc = chardet.detect(raw)["encoding"] or "utf-8"
    df  = pd.read_csv(BytesIO(raw), encoding=enc, delimiter=';', on_bad_lines='skip')
    st.success(f"CSV cargado (encoding: {enc})")

    # Guardar snapshot fin de mes
    today = date.today()
    if st.checkbox("Guardar snapshot mensual", value=(today.day == calendar.monthrange(today.year, today.month)[1])):
        path = f"{HIST_DIR}/{today:%Y-%m}.csv"; df.to_csv(path, index=False)
        st.info(f"Histórico guardado: {path}")

    # ───────── LIMPIEZA BÁSICA ─────────
    df.rename(columns={df.columns[1]: "Descripcion", df.columns[2]: "Familia"}, inplace=True)
    for col in ['Familia', 'Stock balance', 'On Order', 'Back Order Customer', 'Repurchase Price']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['Familia'] = df['Familia'].astype(int)
    df['Precio Unitario (€)'] = df['Repurchase Price'].round(2)
    df['Stock efectivo'] = df['Stock balance'] + df['On Order'] + df['Back Order Customer']

    ventas_cols = [c for c in df.columns if c.startswith('Sales')]
    df[ventas_cols] = df[ventas_cols].apply(pd.to_numeric, errors='coerce').fillna(0)

    season = [c for c in ['Sales Current Period', 'Sales P-3', 'Sales P-6', 'Sales P-9', 'Sales P-12'] if c in df.columns]
    df['Prevision mensual estimada'] = df[season].mean(axis=1).round(1)
    df['Ventas 12m uds'] = df[ventas_cols].sum(axis=1).astype(int)

    # ───────── PEDIDO NORMAL: cubrir 2 meses ─────────
    def pedido_normal(row):
        if (
            row['Precio Unitario (€)'] <= PRICE_LIMIT and
            row['Ventas 12m uds'] >= 2 and
            row['Prevision mensual estimada'] > 0 and
            row['Familia'] not in EXCEP_FAMS
        ):
            objetivo = round(row['Prevision mensual estimada'] * 2)
            return max(0, objetivo - row['Stock efectivo'])
        return 0

    df['Pedido_normal'] = df.apply(pedido_normal, axis=1)

    # ───────── PEDIDO CAMPAÑA (Familia 11) ─────────
    df['Pedido_camp'] = 0
    in_camp = datetime(today.year, *CAMP_START).date() <= today <= datetime(today.year, *CAMP_END).date()
    if in_camp:
        mask = (
            (df['Familia'] == CAMP_FAM) &
            (df['Ventas 12m uds'] >= 2) &
            (df['Prevision mensual estimada'] > 0)
        )
        df.loc[mask, 'Pedido_camp'] = (
            df.loc[mask, 'Prevision mensual estimada'] * COVER_MESES - df.loc[mask, 'Stock efectivo']
        ).clip(lower=0).round()

    # Selección final
    df['Pedido sugerido'] = df[['Pedido_normal', 'Pedido_camp']].max(axis=1)
    df['Valor pedido (€)'] = (df['Pedido sugerido'] * df['Precio Unitario (€)']).round(2)

    cols_out = [
        'Part no', 'Descripcion', 'Familia', 'Stock balance', 'On Order', 'Back Order Customer',
        'Stock efectivo', 'Prevision mensual estimada', 'Ventas 12m uds', 'Precio Unitario (€)',
        'Pedido sugerido', 'Valor pedido (€)'
    ]

    pedido_norm = df[df['Pedido_normal'] > 0][cols_out]
    pedido_camp = df[df['Pedido_camp'] > 0][cols_out]

    # Artículos caros (>1500 €) o familias exentas
    mask_caros = (
        (df['Precio Unitario (€)'] > PRICE_LIMIT) |
        (df['Familia'].isin(EXCEP_FAMS))
    ) & (df['Ventas 12m uds'] >= 2) & (df['Prevision mensual estimada'] > 0)

    pedido_caros = df[mask_caros].copy()
    pedido_caros['Pedido sugerido'] = round(pedido_caros['Prevision mensual estimada'] * 2)
    pedido_caros['Valor pedido (€)'] = (pedido_caros['Pedido sugerido'] * pedido_caros['Precio Unitario (€)']).round(2)
    pedido_caros = pedido_caros[cols_out]

    # ───────── VISUALIZACIÓN ─────────
    st.subheader("📦 Pedido normal (≤ 1 500 €)")
    st.dataframe(pedido_norm)

    if in_camp and not pedido_camp.empty:
        st.subheader("🎯 Pedido campaña – Familia 11")
        st.dataframe(pedido_camp)

    if not pedido_caros.empty:
        st.subheader("💰 Pedido artículos caros o familias 17/18/21")
        st.dataframe(pedido_caros)

    # ───────── DASHBOARD KPI ─────────
    df['Ventas 12m €']  = pd.to_numeric(df['Importe'], errors='coerce').fillna(0)
    df['Valor stock €'] = df['Stock balance'] * df['Precio Unitario (€)']
    ventas_tot = df['Ventas 12m €'].sum(); stock_tot = df['Valor stock €'].sum(); rot = ventas_tot / stock_tot if stock_tot else 0

    st.subheader("📊 KPI global")
    k1,k2,k3 = st.columns(3)
    k1.metric("Ventas 12m (€)", f"{ventas_tot:,.2f}")
    k2.metric("Valor stock (€)", f"{stock_tot:,.2f}")
    k3.metric("Índice rotación", f"{rot:.2f}")

    # Stock sano/muerto (ventas € > 0)
    df['Stock sano'] = df['Ventas 12m €'] > 0
    salud = (
        df.groupby('Stock sano')
          .agg({'Part no':'count','Valor stock €':'sum'})
          .rename(index={True:'Sano', False:'Muerto'})
    )
    salud['% sobre total'] = (salud['Valor stock €']/stock_tot*100).round(2)
    st.subheader("🩺 Stock sano vs muerto")
    st.dataframe(salud.reset_index().rename(columns={'index':'Tipo'}))

    # Observaciones básicas
    df['Observación'] = None
    df.loc[(df['Ventas 12m €'] < 100) & (df['Stock efectivo'] > 10), 'Observación'] = '🔵 Bajo € y stock alto'
    obs = df[df['Observación'].notnull()][['Part no','Descripcion','Familia','Observación','Ventas 12m uds','Ventas 12m €','Stock efectivo']]
    if not obs.empty:
        st.subheader("🔎 Observaciones")
        st.dataframe(obs)

        # ───────── DESCARGAS ─────────
    def to_xlsx(df_, name):
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
            df_.to_excel(w, sheet_name=name[:31], index=False)
        buf.seek(0)
        return buf

    if not pedido_norm.empty:
        st.download_button(
            "📄 Descargar pedidos (≤ 1 500 €)",
            to_xlsx(pedido_norm, 'Pedido'),
            "pedidos_vpim.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        vim_csv = (
            pedido_norm[['Part no', 'Pedido sugerido']]
            .rename(columns={'Part no': 'Articulo', 'Pedido sugerido': 'Pedido'})
            .to_csv(index=False, sep=';', encoding='utf-8')
        )
        st.download_button(
            "📄 Descargar VIM artículos ≤ 1 500 €",
            vim_csv,
            "VIM_para_importar_pedido_normal.csv",
            mime="text/csv"
        )

    if not pedido_camp.empty:
        st.download_button(
            "📄 Descargar pedido campaña",
            to_xlsx(pedido_camp, 'Camp_F11'),
            "pedido_campania_f11.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    if not pedido_caros.empty:
        st.download_button(
            "📄 Descargar Pedido artículos caros",
            to_xlsx(pedido_caros, 'Caros'),
            "Pedido_articulos_caros.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # Informe KPI + observaciones
    kpi_sheet = pd.DataFrame({
        'KPI': ['Ventas 12m (€)', 'Valor stock (€)', 'Índice rotación'],
        'Valor': [ventas_tot, stock_tot, rot]
    })
    sheets_info = {
        'KPI': kpi_sheet,
        'StockSalud': salud.reset_index().rename(columns={'index': 'Tipo'}),
        'Observaciones': obs
    }
    st.download_button(
        "📄 Descargar informe KPI",
        to_xlsx(pd.concat(sheets_info.values()), 'Info'),
        "informe_kpi_vpim.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

except Exception as e:
    st.error(f"Error: {e}")




















