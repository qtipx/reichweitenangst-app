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

# --- 1. DATENBANK ---
MOTOR_SYSTEMS = {
    "Bosch Smart System (Gen4)": {"modes": {"Eco": 0.60, "Tour+": 1.40, "eMTB": 2.50, "Turbo": 3.40}, "efficiency": 0.80, "drag_factor": 0.6, "default_cap": 750},
    "DJI Avinox (M1/M2)": {"modes": {"Eco": 1.0, "Auto": 2.5, "Trail": 4.5, "Turbo": 7.0}, "efficiency": 0.83, "drag_factor": 0.3, "default_cap": 800},
    "Pinion MGU (E1.12)": {"modes": {"Eco": 0.8, "Flow": 1.6, "Flex": 2.8, "Fly": 4.0}, "efficiency": 0.77, "drag_factor": 0.8, "default_cap": 800},
    "Shimano EP801 / EP8": {"modes": {"Eco": 0.6, "Trail": 1.5, "Boost": 3.5}, "efficiency": 0.78, "drag_factor": 0.5, "default_cap": 630}
}

BIKE_WEIGHT, GRAVITY, AIR_DENSITY, CW_AREA, CRR_FOREST = 26.0, 9.81, 1.225, 0.72, 0.045 

st.set_page_config(page_title="Reichweitenangst", layout="wide")

# State Management für Listen
for key in ['charges', 'modes', 'extenders', 'spare_batteries']:
    if key not in st.session_state: st.session_state[key] = []

# --- 2. SIDEBAR (ALLE EINGABEN ZUERST) ---
with st.sidebar:
    st.markdown("<h2 style='text-align: center; color: #F7D106;'>REICHWEITENANGST</h2>", unsafe_allow_html=True)
    sel_motor = st.selectbox("Motor", list(MOTOR_SYSTEMS.keys()), index=0)
    spec = MOTOR_SYSTEMS[sel_motor]
    
    with st.expander("👤 Setup", expanded=True):
        u_weight = st.number_input("Fahrer Kg", 50, 150, 95)
        extra_load = st.number_input("Last Kg", 0, 30, 5)
        temp = st.slider("Temp °C", -10, 35, 12)
        # Dieser Regler muss VOR der Berechnung stehen
        v_flat = st.slider("Ø km/h Ebene", 10, 45, 25)

    with st.expander("🔋 Akkus"):
        m_wh = st.number_input("Hauptakku Wh", 200, 1000, spec['default_cap'])
        if st.button("➕ Extender"): st.session_state.extenders.append({'wh': 250}); st.rerun()
        for i, ext in enumerate(st.session_state.extenders):
            st.session_state.extenders[i]['wh'] = st.number_input(f"Ex {i+1} Wh", 50, 500, ext['wh'])
        if st.button("➕ Ersatz"): st.session_state.spare_batteries.append({'wh': 500}); st.rerun()

    with st.expander("⚡ Strategie"):
        if st.button("➕ Wechsel"): st.session_state.modes.append({'km': 10, 'mode': list(spec['modes'].keys())[0]}); st.rerun()
        for i, m in enumerate(st.session_state.modes):
            st.session_state.modes[i]['km'] = st.number_input(f"Wechsel {i} km", 0, 200, m['km'])
            st.session_state.modes[i]['mode'] = st.selectbox(f"Modus {i}", list(spec['modes'].keys()), index=list(spec['modes'].keys()).index(m['mode']))

# --- 3. DATEN LADEN ---
file = st.file_uploader("GPX laden", type=["gpx"], label_visibility="collapsed")
if file:
    gpx = gpxpy.parse(file)
    pts = []
    d_acc = 0
    for track in gpx.tracks:
        for seg in track.segments:
            for i, p in enumerate(seg.points):
                d = p.distance_3d(seg.points[i-1]) if i > 0 else 0
                d_acc += d
                pts.append({'cum_dist': d_acc/1000, 'dist_diff': d, 'ele': p.elevation, 'lat': p.latitude, 'lon': p.longitude})
    
    # --- 4. BERECHNUNG (ERST HIER!) ---
    df = pd.DataFrame(pts)
    total_w = u_weight + BIKE_WEIGHT + extra_load
    df['ele_diff'] = df['ele'].diff().fillna(0)
    
    # Geschwindigkeit wird hier fix an den Slider v_flat gebunden
    df['v_ms'] = np.where(df['ele_diff'] > 0, 12/3.6, v_flat/3.6)
    df['dur'] = df['dist_diff'] / df['v_ms']
    
    # Akku-System
    sys_cap = m_wh + sum(e['wh'] for e in st.session_state.extenders)
    battery_stack = [{'cap': sys_cap}] + [{'cap': s['wh']} for s in st.session_state.spare_batteries]
    
    curr_idx, cons, last_p = 0, 0, 100.0
    pcts, markers, events = [], [], []
    tf = 1.0 + (max(0, 20 - temp) * 0.008)

    for i in range(len(df)):
        v = df['v_ms'].iloc[i]
        # Physik: Luftwiderstand ist v^3 -> massive Auswirkung bei Speed
        p_air = 0.5 * AIR_DENSITY * (v**3) * CW_AREA
        p_roll = total_w * GRAVITY * CRR_FOREST * v
        p_slope = (total_w * GRAVITY * df['ele_diff'].iloc[i].clip(min=0)) / max(df['dur'].iloc[i], 0.1)
        p_req = p_slope + p_roll + p_air
        
        # Verbrauch
        e_seg = (((p_req * 0.8) * df['dur'].iloc[i] / 3600) / spec['efficiency']) * tf
        cons += e_seg
        
        # Akkuwechsel
        if cons >= battery_stack[curr_idx]['cap'] and curr_idx < len(battery_stack)-1:
            curr_idx += 1; cons = 0; last_p = 100.0
        
        p = max(0, ((battery_stack[curr_idx]['cap'] - cons) / battery_stack[curr_idx]['cap']) * 100)
        pcts.append(p)
        m_val = next((t for t in [90,80,70,60,50,40,30,20,10,0] if last_p > t >= p), np.nan)
        markers.append(m_val); last_p = p

    df['battery_pct'], df['marker'] = pcts, markers
    df['color'] = np.select([df['battery_pct']>20, df['battery_pct']>10, df['battery_pct']>0], ['#00CC96', '#FFD700', '#FF4B4B'], default='#85144b')
    df['z_id'] = (df['color'] != df['color'].shift(1)).cumsum()

    # --- 5. ANZEIGE ---
    st.markdown("### 🚩 Analyse")
    c = st.columns(3)
    c[0].metric("Distanz", f"{df['cum_dist'].iloc[-1]:.1f} km")
    c[1].metric("Restakku", f"{df['battery_pct'].iloc[-1]:.1f} %")
    c[2].metric("Ebene Speed", f"{v_flat} km/h")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['cum_dist'], y=df['ele'], fill='tozeroy', fillcolor='rgba(100,100,100,0.1)', line=dict(width=0)))
    for zid in df['z_id'].unique():
        z_df = df[df['z_id'] == zid]
        fig.add_trace(go.Scatter(x=z_df['cum_dist'], y=z_df['ele'], mode='lines', line=dict(color=z_df['color'].iloc[-1], width=5), showlegend=False))
    
    st.plotly_chart(fig, use_container_width=True)
