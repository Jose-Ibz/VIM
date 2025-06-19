import os
import calendar
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st
import chardet

# ─────────────────────────────────────────────
# CONFIGURACIÓN GLOBAL
# ─────────────────────────────────────────────
HIST_DIR = "historico"
os.makedirs(HIST_DIR, exist_ok=True)

# Campaña fija (Familia 11)
CAMP_FAM       = 11
CAMP_START     = (9, 16)   # 16‑sep
CAMP_END       = (11, 22)  # 22‑nov
COVER_MESES    = 9         # cubrir 9 meses

st.title("VPIM – Pedido + KPI con campaña Familia 11")

# ─────────────────────────────────────────────
# 1 · SUBIR CSV INVENTARIO
# ─────────────────────────────────────────────
uploaded = st.file_uploader("Sube tu inventario CSV", type=["csv"])
if uploaded is not None:
    try:
        # 1.1 Detectar codificación
        raw = uploaded.read()
        encoding = chardet.detect(raw)["encoding"] or "utf-8"
        df = pd.read_csv(BytesIO(raw), encoding=encoding, delimiter=';', on_bad_lines='skip')
        st.success(f"CSV cargado (encoding: {encoding})")

        # 1.2 Snapshot fin de mes
        today = date.today()
        if st.checkbox("Guardar histórico mensual", value=(today.day == calendar.monthrange(today.year, today.month)[1])):
            snap = f"{HIST_DIR}/{today:%Y-%m}.csv"; df.to_csv(snap, index=False); st.info(f"Guardado: {snap}")

        # ───────────────────────── 2 · LIMPIEZA ─────────────────────────
        df.rename(columns={df.columns[1]: "Descripcion", df.columns[2]: "Familia"}, inplace=True)
        df['Familia'] = pd.to_numeric(df['Familia'], errors='coerce').fillna(-1).astype(int)
        df['Repurchase Price'] = pd.to_numeric(df['Repurchase Price'], errors='coerce').fillna(0)
        df['Stock balance']    = pd.to_numeric(df['Stock balance'], errors='coerce').fillna(0)
        df['Precio Unitario (€)'] = df['Repurchase Price'].round(2)

        # Previsión estacional (t, t‑3, t‑6, t‑9, t‑12)
        ventas_cols = [c for c in df.columns if c.startswith('Sales')]
        df[ventas_cols] = df[ventas_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
        season = [c for c in ['Sales Current Period','Sales P-3','Sales P-6','Sales P-9','Sales P-12'] if c in df.columns]
        df['Prevision mensual estimada'] = df[season].mean(axis=1).round(1)
        df['Ventas 12m uds'] = df[ventas_cols].sum(axis=1).astype(int)

        # ───────────────────────── 3 · SS / EOQ ─────────────────────────
        reglas = pd.read_excel("tabla_pedidos.xlsx")
        def ss_eoq(prev, price):
            if price > 1000:
                return 0, 0
            ss = eoq = 0
            for _, r in reglas.iterrows():
                if r['Prevision_min'] <= prev <= r['Prevision_max'] and price <= r['Precio_max']:
                    ss, eoq = r['SS'], r['EOQ']
                    break
            if (ss, eoq) in [(0, 0), (-1, -1)] and prev > 0:
                ss = max(1, round(prev * 0.5))
                eoq = max(1, round(prev * 1.5))
            return ss, eoq
        df[['SS', 'EOQ']] = df.apply(lambda r: pd.Series(ss_eoq(r['Prevision mensual estimada'], r['Precio Unitario (€)'])), axis=1)

        # ───────────────────────── 4 · PEDIDOS ─────────────────────────
        start_camp = datetime(today.year, *CAMP_START).date()
        end_camp   = datetime(today.year, *CAMP_END).date()
        in_camp    = start_camp <= today <= end_camp

        df['Pedido_normal'] = df.apply(lambda r: r['EOQ'] if r['EOQ']>0 and r['Stock balance']<r['SS'] else 0, axis=1)
        df['Pedido_camp']   = 0
        if in_camp:
            mask = df['Familia'] == CAMP_FAM
            df.loc[mask, 'Pedido_camp'] = (df.loc[mask, 'Prevision mensual estimada'] * COVER_MESES - df.loc[mask, 'Stock balance']).clip(lower=0).round()

        df['Pedido sugerido']     = df['Pedido_camp'].where(df['Pedido_camp']>0, df['Pedido_normal'])
        df['Valor pedido (€)']    = (df['Pedido sugerido'] * df['Precio Unitario (€)']).round(2)

        cols = ['Part no','Descripcion','Familia','Stock balance','Prevision mensual estimada','Ventas 12m uds','Precio Unitario (€)','SS','EOQ','Pedido sugerido','Valor pedido (€)']
        df_camp = df[(df['Familia']==CAMP_FAM)&(df['Pedido_camp']>0)][cols]
        df_norm = df[(df['Pedido sugerido']>0) & (~((df['Familia']==CAMP_FAM)&in_camp))][cols]

        if in_camp and not df_camp.empty:
            st.subheader("🎯 Pedido campaña Familia 11")
            st.dataframe(df_camp)
        st.subheader("📦 Pedido normal")
        st.dataframe(df_norm)

        # ───────────────────────── 5 · KPI ─────────────────────────
        df['Ventas 12m €']  = pd.to_numeric(df['Importe'], errors='coerce').fillna(0)
        df['Valor stock €'] = df['Stock balance'] * df['Precio Unitario (€)']
        ventas_tot = df['Ventas 12m €'].sum()
        stock_tot  = df['Valor stock €'].sum()
        rotacion   = ventas_tot / stock_tot if stock_tot else 0

        st.subheader("🔢 KPI global")
        st.write(f"Ventas 12 m (€): **{ventas_tot:,.2f} €**")
        st.write(f"Valor stock (€): **{stock_tot:,.2f} €**")
        st.write(f"Índice rotación: **{rotacion:.2f}**")

        df['Stock sano'] = df['Ventas 12m €'] > 0
        salud = df.groupby('Stock sano').agg({'Part no':'count','Valor stock €':'sum'}).rename(index={True:'Sano',False:'Muerto'})
        salud['% sobre total'] = (salud['Valor stock €'] / stock_tot * 100).round(2)
        st.subheader("🩺 Stock sano vs muerto")
        st.dataframe(salud.reset_index().rename(columns={'index':'Tipo'}))

        # Observaciones básicas
        df['Observación'] = None
        df.loc[(df['Ventas 12m €']<100) & (df['Stock balance']>10), 'Observación'] = '🔵 Bajo € y alto stock'
        obs = df[df['Observación'].notnull()][['Part no','Descripcion','Familia','Observación','Ventas 12m uds','Ventas 12m €','Stock balance']]
        if not obs.empty:
            st.subheader("🔎 Observaciones")
            st.dataframe(obs)

        # ───────────────────────── 6 · EXPORTACIÓN EXCEL ─────────────────────────
        def make_xlsx(sheets: dict) -> BytesIO:
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                for name, frame in sheets.items():
                    frame.to_excel(w, sheet_name=name[:31], index=False)
            buf.seek(0)
            return buf

        sheets_ped = {"Pedido": df_norm}
        if in_camp and not df_camp.empty:
            sheets_ped["Camp_F11"] = df_camp
        st.download_button(
            "📄 Descargar pedidos",
            make_xlsx(sheets_ped),
            file_name="pedidos_vpim.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # Informe KPI + observaciones
        kpi_sheet = pd.DataFrame({
            "KPI": ["Ventas 12m (€)", "Valor stock (€)", "Índice rotación"],
            "Valor": [ventas_tot, stock_tot, rotacion]
        })
        sheets_info = {
            "KPI": kpi_sheet,
            "StockSalud": salud.reset_index().rename(columns={"index": "Tipo"}),
            "Observaciones": obs
        }
        st.download_button(
            "📄 Descargar informe KPI",
            make_xlsx(sheets_info),
            file_name="informe_kpi_vpim.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"Error: {e}")
