import streamlit as st
import gpxpy
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import folium
from folium.plugins import Fullscreen
from streamlit_folium import folium_static
import time
import os

# --- DATENBANK ---
MOTOR_SYSTEMS = {
    "Bosch Smart System (Gen4)": {"modes": {"Eco": 0.60, "Tour+": 1.40, "eMTB": 2.50, "Turbo": 3.40}, "efficiency": 0.80, "drag_factor": 0.6, "default_cap": 750},
    "DJI Avinox (M1/M2)": {"modes": {"Eco": 1.0, "Auto": 2.5, "Trail": 4.5, "Turbo": 7.0, "Boost": 8.0}, "efficiency": 0.83, "drag_factor": 0.3, "default_cap": 800},
    "Pinion MGU (E1.12)": {"modes": {"Eco": 0.8, "Flow": 1.6, "Flex": 2.8, "Fly": 4.0}, "efficiency": 0.77, "drag_factor": 0.8, "default_cap": 800},
    "Specialized / Brose Mag S": {"modes": {"Eco": 0.35, "Trail": 1.0, "Turbo": 4.1}, "efficiency": 0.82, "drag_factor": 0.2, "default_cap": 700},
    "Shimano EP801 / EP8": {"modes": {"Eco": 0.6, "Trail": 1.5, "Boost": 3.5}, "efficiency": 0.78, "drag_factor": 0.5, "default_cap": 630},
    "Bosch CX (Gen2)": {"modes": {"Eco": 0.50, "Tour": 1.20, "Sport": 2.10, "Turbo": 3.00}, "efficiency": 0.74, "drag_factor": 1.2, "default_cap": 500},
    "Yamaha PW-X3": {"modes": {"+Eco": 0.50, "Eco": 1.00, "Std": 1.90, "High": 2.80, "EXPW": 3.60}, "efficiency": 0.79, "drag_factor": 0.6, "default_cap": 720}
}

BIKE_WEIGHT, GRAVITY, AIR_DENSITY, CW_AREA, CRR_FOREST = 26.0, 9.81, 1.225, 0.72, 0.045 

st.set_page_config(page_title="Reichweitenangst", layout="wide")

# State Management
for key in ['charges', 'modes', 'extenders', 'spare_batteries']:
    if key not in st.session_state: st.session_state[key] = []
if 'points_data' not in st.session_state: st.session_state.points_data = None

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("reichweitenangst.png"):
        st.image("reichweitenangst.png", use_container_width=True)
    st.markdown("<h2 style='text-align: center; color: #F7D106;'>REICHWEITENANGST</h2>", unsafe_allow_html=True)
    
    sel_motor = st.selectbox("Motor", list(MOTOR_SYSTEMS.keys()), index=0)
    spec = MOTOR_SYSTEMS[sel_motor]
    
    if not st.session_state.modes:
        st.session_state.modes = [{'id': 1, 'km': 0, 'mode': list(spec['modes'].keys())[-1]}]
    
    with st.expander("👤 Setup"):
        c1, c2 = st.columns(2)
        u_weight, extra_load = c1.number_input("Fahrer Kg", 50, 150, 95), c2.number_input("Last Kg", 0, 30, 5)
        temp = st.slider("Temp °C", -10, 35, 12)
        # CRITICAL: Dieser Wert muss in run_calc landen
        v_flat = st.slider("Ø km/h Ebene", 10, 45, 25)

    with st.expander("🔋 Akkus", expanded=True):
        m_wh = st.number_input("Hauptakku Wh", 200, 1000, spec['default_cap'], step=10)
        st.divider()
        h1, h2 = st.columns([3, 1])
        h1.markdown("**+ Extender**")
        if h2.button("➕", key="add_ex"): st.session_state.extenders.append({'wh': 250}); st.rerun()
        for i, ext in enumerate(st.session_state.extenders):
            col1, col2 = st.columns([4, 1])
            st.session_state.extenders[i]['wh'] = col1.number_input("Wh", 50, 500, ext['wh'], key=f"ex_{i}", label_visibility="collapsed")
            if col2.button("🗑️", key=f"dex_{i}"): st.session_state.extenders.pop(i); st.rerun()

    with st.expander("⚡ Strategie"):
        if st.button("➕ Wechsel", use_container_width=True): 
            st.session_state.modes.append({'id': time.time(), 'km': 10, 'mode': list(spec['modes'].keys())[0]}); st.rerun()
        for i, m in enumerate(st.session_state.modes):
            mc1, mc2, mc3 = st.columns([1.2, 2.5, 0.8])
            st.session_state.modes[i]['km'] = mc1.number_input("km", 0, 250, m['km'], key=f"mkm_{i}", label_visibility="collapsed", disabled=(i==0))
            st.session_state.modes[i]['mode'] = mc2.selectbox("Mod", list(spec['modes'].keys()), key=f"mtyp_{i}", label_visibility="collapsed", index=list(spec['modes'].keys()).index(m['mode']))
            if i > 0 and mc3.button("🗑️", key=f"mdel_{i}"): st.session_state.modes.pop(i); st.rerun()

# --- RECHNERKERN ---
def run_calc(points, weight, temp, v_flat_val, motor_name):
    df = pd.DataFrame(points)
    m_spec = MOTOR_SYSTEMS[motor_name]
    df['ele_diff'], df['dist_diff'] = df['ele'].diff().fillna(0), df['dist_diff'].fillna(0)
    
    # Geschwindigkeitsszenario basierend auf dem Slider
    df['v_ms'] = np.where(df['ele_diff'] > 0, 12/3.6, v_flat_val/3.6)
    df['dur'] = np.where(df['v_ms'] > 0, df['dist_diff'] / df['v_ms'], 0.1)
    
    main_cap = m_wh + sum(e['wh'] for e in st.session_state.extenders)
    
    curr_idx, cons, last_p = 0, 0, 100.0
    pcts, markers = [], []
    sorted_modes = sorted([dict(m) for m in st.session_state.modes], key=lambda x: x['km'])
    tf = 1.0 + (max(0, 20 - temp) * 0.008) # Temperaturfaktor

    for i in range(len(df)):
        km, v = df['cum_dist'].iloc[i], df['v_ms'].iloc[i]
        
        # Leistung P = Steigung + Rollwiderstand + Luftwiderstand (v^3)
        p_air = 0.5 * AIR_DENSITY * v**3 * CW_AREA
        p_roll = weight * GRAVITY * CRR_FOREST * v
        p_slope = (weight * GRAVITY * df['ele_diff'].iloc[i].clip(min=0)) / df['dur'].iloc[i]
        p_req = p_slope + p_roll + p_air
        
        m_curr = next((m['mode'] for m in reversed(sorted_modes) if km >= m['km']), list(m_spec['modes'].keys())[-1])
        # Motor liefert Differenz zwischen P_req und Eigenleistung (vereinfacht)
        p_mot = p_req - min(p_req / (1 + m_spec['modes'][m_curr]), 150)
        
        # Energieverbrauch in Wh für das Segment
        e_seg = (m_spec['drag_factor'] * (df['dist_diff'].iloc[i]/1000)) if df['ele_diff'].iloc[i] <= 0 else (((max(0, p_mot) * df['dur'].iloc[i] / 3600) / m_spec['efficiency']) * tf)
        
        cons += e_seg
        p = max(0, ((main_cap - cons) / main_cap) * 100)
        pcts.append(p)
        m_val = next((t for t in [90, 80, 70, 60, 50, 40, 30, 20, 10, 0] if last_p > t >= p), np.nan)
        markers.append(m_val); last_p = p

    df['battery_pct'], df['marker'] = pcts, markers
    df['color'] = np.select([df['battery_pct']>20, df['battery_pct']>10, df['battery_pct']>0], ['#00CC96', '#FFD700', '#FF4B4B'], default='#85144b')
    df['z_id'] = (df['color'] != df['color'].shift(1)).cumsum()
    return df

# --- UI MAIN ---
file = st.file_uploader("GPX laden", type=["gpx"], label_visibility="collapsed")
if file:
    gpx = gpxpy.parse(file)
    pts, d_acc = [], 0
    for track in gpx.tracks:
        for seg in track.segments:
            for i, p in enumerate(seg.points):
                d = p.distance_3d(seg.points[i-1]) if i > 0 else 0
                d_acc += d
                pts.append({'cum_dist': d_acc/1000, 'dist_diff': d, 'ele': p.elevation, 'lat': p.latitude, 'lon': p.longitude})
    st.session_state.points_data = pts

if st.session_state.points_data:
    # WICHTIG: v_flat wird hier an die Berechnung übergeben
    df = run_calc(st.session_state.points_data, u_weight+BIKE_WEIGHT+extra_load, temp, v_flat, sel_motor)
    
    st.markdown(f"### 🚩 Tour Analyse")
    c = st.columns(4)
    c[0].metric("Distanz", f"{df['cum_dist'].iloc[-1]:.1f} km")
    c[1].metric("Höhenmeter", f"{df['ele'].diff().clip(lower=0).sum():.0f} hm ↑")
    c[2].metric("Restakku", f"{df['battery_pct'].iloc[-1]:.1f} %")
    c[3].metric("Ø Speed Ebene", f"{v_flat} km/h")

    # Plotly Graph
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['cum_dist'], y=df['ele'], fill='tozeroy', fillcolor='rgba(100,100,100,0.1)', line=dict(width=0), hoverinfo='skip'))
    for zid in df['z_id'].unique():
        z_df = df[df['z_id'] == zid]
        fig.add_trace(go.Scatter(x=z_df['cum_dist'], y=z_df['ele'], mode='lines', line=dict(color=z_df['color'].iloc[-1], width=5), showlegend=False))
    
    m_df = df[df['marker'].notnull()]
    if not m_df.empty:
        fig.add_trace(go.Scatter(x=m_df['cum_dist'], y=m_df['ele']+20, mode='markers+text', text=[f"{int(v)}%" for v in m_df['marker']], textfont=dict(color="white"), textposition="top center", marker=dict(color='white', size=4)))
    
    st.plotly_chart(fig, use_container_width=True)
