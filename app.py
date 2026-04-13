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
for key in ['extenders', 'spare_batteries', 'modes', 'charges']:
    if key not in st.session_state: st.session_state[key] = []

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("reichweitenangst.png"):
        st.image("reichweitenangst.png", use_container_width=True)
    st.markdown("<h2 style='text-align: center; color: #F7D106;'>REICHWEITENANGST</h2>", unsafe_allow_html=True)
    
    sel_motor = st.selectbox("Motor", list(MOTOR_SYSTEMS.keys()))
    spec = MOTOR_SYSTEMS[sel_motor]
    
    with st.expander("👤 Setup", expanded=True):
        c1, c2 = st.columns(2)
        u_weight = c1.number_input("Fahrer Kg", 50, 150, 95)
        extra_load = c2.number_input("Last Kg", 0, 30, 5)
        temp = st.slider("Temp °C", -10, 35, 20)
        # HIER IST DER REGLER
        v_flat = st.slider("Ø km/h Ebene", 10, 45, 25)

    with st.expander("🔋 Akkus"):
        m_wh = st.number_input("Hauptakku Wh", 200, 1000, spec['default_cap'])

# --- RECHNER ---
def run_physics_calc(points, weight, temperature, speed_flat, motor_name, battery_wh):
    df = pd.DataFrame(points)
    m_spec = MOTOR_SYSTEMS[motor_name]
    
    df['ele_diff'] = df['ele'].diff().fillna(0)
    df['dist_diff'] = df['dist_diff'].fillna(0)
    
    # Geschwindigkeit in m/s (Ebene vs Steigung)
    df['v_ms'] = np.where(df['ele_diff'] > 0, 12/3.6, speed_flat/3.6)
    df['dur'] = df['dist_diff'] / df['v_ms']
    
    total_cons = 0
    tf = 1.0 + (max(0, 20 - temperature) * 0.008)
    
    pcts = []
    for i in range(len(df)):
        v = df['v_ms'].iloc[i]
        # Luftwiderstand (steigt kubisch!)
        p_air = 0.5 * AIR_DENSITY * (v**3) * CW_AREA
        p_roll = weight * GRAVITY * CRR_FOREST * v
        p_slope = (weight * GRAVITY * df['ele_diff'].iloc[i].clip(min=0)) / max(df['dur'].iloc[i], 0.1)
        
        p_req = p_slope + p_roll + p_air
        # Motor-Anteil (Turbo Modus Annahme für maximalen Effekt des Speeds)
        p_mot = p_req - min(p_req / (1 + 3.4), 150) 
        
        e_seg = ((max(0, p_mot) * df['dur'].iloc[i] / 3600) / m_spec['efficiency']) * tf
        total_cons += e_seg
        
        current_pct = max(0, ((battery_wh - total_cons) / battery_wh) * 100)
        pcts.append(current_pct)
        
    df['battery_pct'] = pcts
    return df

# --- MAIN ---
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
    
    # BERECHNUNG STARTEN
    res_df = run_physics_calc(pts, u_weight+BIKE_WEIGHT+extra_load, temp, v_flat, sel_motor, m_wh)
    
    # ECKDATEN
    st.markdown(f"### 🚩 Tour Analyse")
    cols = st.columns(4)
    cols[0].metric("Distanz", f"{res_df['cum_dist'].iloc[-1]:.1f} km")
    cols[1].metric("Höhenmeter", f"{res_df['ele'].diff().clip(lower=0).sum():.0f} hm ↑")
    cols[2].metric("Restakku", f"{res_df['battery_pct'].iloc[-1]:.1f} %")
    cols[3].metric("Ø Speed Ebene", f"{v_flat} km/h")

    # GRAPH
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=res_df['cum_dist'], y=res_df['ele'], mode='lines', line=dict(color='#00CC96', width=4), fill='tozeroy', fillcolor='rgba(0,204,150,0.1)'))
    st.plotly_chart(fig, use_container_width=True)
