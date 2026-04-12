import streamlit as st
import gpxpy
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
import os

# --- KALIBRIERTE PHYSIKALISCHE KONSTANTEN (Optimiert am 12.04.2026) ---
BIKE_WEIGHT, GRAVITY, AIR_DENSITY = 26.0, 9.81, 1.225
CW_AREA, EFFICIENCY, CRR_FOREST = 0.72, 0.78, 0.045 

BOSCH_MODES = {
    "Eco": {"support": 0.60}, "Tour": {"support": 1.40}, 
    "PWR/eMTB": {"support": 2.50}, "Turbo": {"support": 3.40}
}

st.set_page_config(page_title="Reichweitenangst", layout="wide")

if 'charges' not in st.session_state: st.session_state.charges = []
if 'points_data' not in st.session_state: st.session_state.points_data = None

# --- SIDEBAR: SETUP ---
with st.sidebar:
    if os.path.exists("reichweitenangst.png"):
        st.image("reichweitenangst.png", use_container_width=True)
    st.markdown("<h2 style='text-align: center; color: #F7D106; font-size: 26px; font-weight: 900; margin: 0;'>REICHWEITENANGST</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 10px; color: #888; margin-bottom: 5px;'>m@lissner.de</p>", unsafe_allow_html=True)
    
    with st.expander("👤 Setup & Gewicht", expanded=True):
        c1, c2 = st.columns(2)
        u_weight = c1.number_input("Kg", 50, 150, 95)
        extra_load = c2.number_input("+Kg", 0, 30, 5)
        rider_type = st.select_slider("Fitness", options=["Gering", "Mittel", "Sportlich"], value="Mittel")
        temp = st.slider("Temp °C", -10, 35, 12)
        avg_speed_flat = st.slider("Ø km/h Ebene", 20, 45, 28)

    with st.expander("🔋 Bike & Akkus"):
        has_extender = st.checkbox("Extender (500Wh)", value=False)
        spare_1 = st.checkbox("Ersatz 1 (625Wh)")
        spare_2 = st.checkbox("Ersatz 2 (500Wh)")

    with st.expander("⚡ Modusstrategie", expanded=True):
        mode_1 = st.selectbox("Start", list(BOSCH_MODES.keys()), index=3) # Default: Turbo
        switch_km = st.number_input("Wechsel bei km", 0, 150, 100) # Default: 100km
        mode_2 = st.selectbox("Folge", list(BOSCH_MODES.keys()), index=1) # Folge: Tour

# --- HAUPTFENSTER ---
col_main_1, col_main_2 = st.columns([2, 1])

with col_main_1:
    st.subheader("🗺️ Tour")
    source = st.radio("Quelle", ["GPX-Upload", "Eigene Werte"], horizontal=True, label_visibility="collapsed")
    if source == "GPX-Upload":
        file = st.file_uploader("GPX Datei", type=["gpx"], label_visibility="collapsed")
        if file:
            gpx = gpxpy.parse(file)
            pts, dist_acc = [], 0
            for track in gpx.tracks:
                for seg in track.segments:
                    for i, p in enumerate(seg.points):
                        d = p.distance_3d(seg.points[i-1]) if i > 0 else 0
                        dist_acc += d
                        pts.append({'cum_dist': dist_acc/1000, 'dist_diff': d, 'ele': p.elevation})
            st.session_state.points_data = pts
    else:
        c_m1, c_m2 = st.columns(2)
        m_dist = c_m1.number_input("km Gesamt", 1, 200, 35)
        m_ele = c_m2.number_input("hm Gesamt", 0, 5000, 1000)
        st.session_state.points_data = [{'cum_dist': (m_dist/100)*i, 'dist_diff': (m_dist*1000)/100 if i>0 else 0, 'ele': (m_ele/100)*i} for i in range(101)]

with col_main_2:
    st.subheader("☕ Ladestopps")
    for idx, c in enumerate(st.session_state.charges):
        l_col1, l_col2 = st.columns([2, 1])
        st.session_state.charges[idx]['km'] = l_col1.number_input(f"km P{idx+1}", 0, 150, c['km'], key=f"k_{c['id']}")
        st.session_state.charges[idx]['pct'] = l_col2.number_input(f"% P{idx+1}", 1, 100, c['pct'], key=f"p_{c['id']}")
    b1, b2 = st.columns(2)
    if b1.button("➕"): st.session_state.charges.append({'id': int(time.time()*1000), 'km': 25, 'pct': 80}); st.rerun()
    if b2.button("🗑️"): st.session_state.charges = []; st.rerun()

# --- RECHNERKERN ---
def run_calc(points, weight, capacity, fitness, switch, t_val, charges):
    df = pd.DataFrame(points)
    base_w = {"Gering": 85, "Mittel": 125, "Sportlich": 170}[fitness]
    df['ele_diff'], df['dist_diff'] = df['ele'].diff().fillna(0), df['dist_diff'].fillna(0)
    df['v_ms'] = np.where(df['ele_diff'] > 0, 12/3.6, avg_speed_flat/3.6)
    df['dur'] = np.where(df['v_ms'] > 0, df['dist_diff'] / df['v_ms'], 0.1)
    
    cons, pcts, markers, events, last_p = 0, [], [], [], 100.0
    active_c = sorted([dict(c) for c in charges], key=lambda x: x['km'])
    tf = 1.0 + (max(0, 20 - t_val) * 0.008)

    for i in range(len(df)):
        km = df['cum_dist'].iloc[i]
        is_c = False
        if active_c and km >= active_c[0]['km']:
            c = active_c.pop(0)
            target = capacity * (1 - c['pct']/100)
            if cons > target: cons = target
            is_c = True
        
        p_req = ((weight * 9.81 * df['ele_diff'].iloc[i].clip(min=0)) / df['dur'].iloc[i]) + \
                (weight * 9.81 * CRR_FOREST * df['v_ms'].iloc[i]) + (0.5 * AIR_DENSITY * df['v_ms'].iloc[i]**3 * CW_AREA)
        
        if df['ele_diff'].iloc[i] <= 0:
            e_seg = 0.7 * (df['dist_diff'].iloc[i] / 1000)
        else:
            support = BOSCH_MODES[mode_1 if km < switch else mode_2]['support']
            p_motor = p_req - min(p_req / (1 + support), base_w * 1.5)
            e_seg = ((max(0, p_motor) * df['dur'].iloc[i] / 3600) / EFFICIENCY) * tf
            
        cons += e_seg
        p = max(0, ((capacity - cons) / capacity) * 100)
        pcts.append(p); events.append(is_c)
        markers.append(next((t for t in [90, 80, 70, 60, 50, 40, 30, 20, 10, 0] if last_p > t >= p), None))
        last_p = p
    df['battery_pct'], df['marker'], df['is_charge'] = pcts, markers, events
    return df

# --- DASHBOARD ---
if st.session_state.points_data:
    st.divider()
    t_cap = 625 + (500 if has_extender else 0) + (625 if spare_1 else 0) + (500 if spare_2 else 0)
    df = run_calc(st.session_state.points_data, u_weight+BIKE_WEIGHT+extra_load, t_cap, rider_type, switch_km, temp, st.session_state.charges)
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Distanz", f"{df['cum_dist'].iloc[-1]:.1f} km"); m2.metric("hm ↑", f"{df['ele_diff'].clip(lower=0).sum():.0f} m")
    m3.metric("Restakku", f"{df['battery_pct'].iloc[-1]:.1f} %"); m4.metric("Status", "✅ OK" if df['battery_pct'].iloc[-1] > 0 else "🚨 LEER")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['cum_dist'], y=df['ele'], fill='tozeroy', line=dict(width=0), fillcolor='rgba(100,100,100,0.1)', hoverinfo='skip'))
    df['color'] = np.select([df['battery_pct']>20, df['battery_pct']>10, df['battery_pct']>0], ['#00CC96', '#FFD700', '#FF851B'], default='#85144b')
    df['z_id'] = (df['color'] != df['color'].shift(1)).cumsum()
    for zid in df['z_id'].unique():
        z_df = df[df['z_id'] == zid]
        if zid > 1: z_df = pd.concat([df[df['z_id'] == zid-1].iloc[[-1]], z_df])
        fig.add_trace(go.Scatter(x=z_df['cum_dist'], y=z_df['ele'], mode='lines', line=dict(color=z_df['color'].iloc[-1], width=5), hoverinfo='skip'))
    m_pts = df[df['marker'].notnull()]
    if not m_pts.empty: fig.add_trace(go.Scatter(x=m_pts['cum_dist'], y=m_pts['ele'], mode='markers+text', text=[f"{int(m)}%" for m in m_pts['marker']], textposition="top center", marker=dict(color='white', size=8, line=dict(color='red', width=1))))
    c_pts = df[df['is_charge'] == True]
    if not c_pts.empty: fig.add_trace(go.Scatter(x=c_pts['cum_dist'], y=c_pts['ele'], mode='markers', marker=dict(color='#F7D106', size=22, symbol='star')))
    fig.update_layout(xaxis_title="km", yaxis_title="Höhe (m)", template="plotly_dark", height=550, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)