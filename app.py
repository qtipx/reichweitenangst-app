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

# --- 1. MOTOREN-DATENBANK (17 Modelle) ---
MOTOR_SYSTEMS = {
    "Bosch Smart System (Gen4)": {"modes": {"Eco": 0.60, "Tour+": 1.40, "eMTB": 2.50, "Turbo": 3.40}, "efficiency": 0.82},
    "Bosch CX (Gen2 - Ritzel)": {"modes": {"Eco": 0.50, "Tour": 1.20, "Sport": 2.10, "Turbo": 3.00}, "efficiency": 0.74},
    "Bosch Active Line Plus": {"modes": {"Eco": 0.40, "Tour": 1.00, "Sport": 1.80, "Turbo": 2.70}, "efficiency": 0.80},
    "Shimano EP801 / EP8": {"modes": {"Eco": 0.60, "Trail": 1.50, "Boost": 3.50}, "efficiency": 0.79},
    "Shimano STEPS E8000": {"modes": {"Eco": 0.50, "Trail": 1.10, "Boost": 3.00}, "efficiency": 0.75},
    "Shimano E6100": {"modes": {"Eco": 0.40, "Norm": 1.00, "High": 2.00}, "efficiency": 0.78},
    "Specialized / Brose Mag S": {"modes": {"Eco": 0.35, "Trail": 1.00, "Turbo": 4.10}, "efficiency": 0.82},
    "Specialized 1.3 (Brose Old)": {"modes": {"Eco": 0.35, "Trail": 0.90, "Turbo": 3.20}, "efficiency": 0.79},
    "Specialized SL 1.1 / 1.2": {"modes": {"Eco": 0.35, "Trail": 0.60, "Turbo": 1.00}, "efficiency": 0.84},
    "DJI Avinox (M1/M2)": {"modes": {"Eco": 1.00, "Auto": 2.50, "Trail": 4.50, "Turbo": 7.00}, "efficiency": 0.85},
    "Pinion MGU (E1.12)": {"modes": {"Eco": 0.80, "Flow": 1.60, "Flex": 2.80, "Fly": 4.00}, "efficiency": 0.77},
    "Yamaha PW-X3": {"modes": {"+Eco": 0.50, "Eco": 1.00, "Std": 1.90, "High": 2.80, "EXPW": 3.60}, "efficiency": 0.79},
    "Yamaha PW-ST": {"modes": {"+Eco": 0.50, "Eco": 1.00, "Std": 1.90, "High": 2.80}, "efficiency": 0.77},
    "Giant SyncDrive Pro": {"modes": {"Eco": 1.00, "Basic": 1.75, "Active": 2.50, "Sport": 3.00, "Power": 3.60}, "efficiency": 0.80},
    "Fazua Ride 60": {"modes": {"Breeze": 0.60, "River": 1.20, "Rocket": 2.50}, "efficiency": 0.83},
    "TQ HPR50": {"modes": {"Eco": 0.40, "Mid": 1.00, "High": 2.00}, "efficiency": 0.85},
    "Mahle X20 / X35": {"modes": {"Eco": 0.30, "Mid": 0.60, "High": 1.00}, "efficiency": 0.86}
}

BIKE_WEIGHT, GRAVITY, AIR_DENSITY, CW_AREA, CRR = 26.0, 9.81, 1.225, 0.58, 0.012 

st.set_page_config(page_title="Reichweitenangst", layout="wide")

for key in ['charges', 'modes', 'extenders', 'spare_batteries']:
    if key not in st.session_state: st.session_state[key] = []

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("reichweitenangst.png"):
        st.image("reichweitenangst.png", use_container_width=True)
    st.markdown("<h2 style='text-align: center; color: #F7D106;'>REICHWEITENANGST</h2>", unsafe_allow_html=True)
    
    sel_motor = st.selectbox("Motor", list(MOTOR_SYSTEMS.keys()), index=0)
    spec = MOTOR_SYSTEMS[sel_motor]
    
    with st.expander("👤 Setup", expanded=True):
        c1, c2 = st.columns(2)
        u_weight = c1.number_input("Fahrer Kg", 50, 150, 95)
        extra_load = c2.number_input("Last Kg", 0, 30, 5)
        temp = st.slider("Temp °C", -10, 35, 12)
        v_flat = st.slider("Ø km/h Ebene", 10, 45, 25)
        # Korrekturwert -1 bis +1, Default 0
        k_val = st.slider("Korrekturfaktor", -1.0, 1.0, 0.0, 0.05)
        k_factor = 1.0 + k_val

    with st.expander("🔋 Akkus", expanded=True):
        m_wh = st.number_input("Hauptakku Wh", 200, 1000, 625)
        if st.button("➕ Extender"): st.session_state.extenders.append({'wh': 250}); st.rerun()
        for i, ext in enumerate(st.session_state.extenders):
            st.session_state.extenders[i]['wh'] = st.number_input(f"Ex {i+1} Wh", 50, 500, ext['wh'])
        if st.button("➕ Ersatz"): st.session_state.spare_batteries.append({'wh': 625}); st.rerun()
        for i, sp in enumerate(st.session_state.spare_batteries):
            st.session_state.spare_batteries[i]['wh'] = st.number_input(f"Ersatz {i+1} Wh", 200, 1000, sp['wh'])

    with st.expander("⚡ Strategie"):
        if st.button("➕ Wechsel"): st.session_state.modes.append({'km': 10, 'mode': list(spec['modes'].keys())[0]}); st.rerun()
        if not st.session_state.modes: st.session_state.modes = [{'km': 0, 'mode': list(spec['modes'].keys())[-1]}]
        for i, m in enumerate(st.session_state.modes):
            st.session_state.modes[i]['km'] = st.number_input(f"km {i}", 0, 250, m['km'], key=f"mkm_{i}")
            st.session_state.modes[i]['mode'] = st.selectbox(f"Modus {i}", list(spec['modes'].keys()), index=list(spec['modes'].keys()).index(m['mode']) if m['mode'] in spec['modes'] else 0, key=f"mtyp_{i}")

    with st.expander("☕ Ladestopps"):
        if st.button("➕ Laden"): st.session_state.charges.append({'km': 30, 'pct': 80}); st.rerun()
        for i, c in enumerate(st.session_state.charges):
            lc1, lc2 = st.columns(2)
            st.session_state.charges[i]['km'] = lc1.number_input(f"km {i}", 0, 250, c['km'], label_visibility="collapsed")
            st.session_state.charges[i]['pct'] = lc2.number_input(f"% {i}", 1, 100, c['pct'], label_visibility="collapsed")

# --- RECHNER ---
file = st.file_uploader("GPX laden", type=["gpx"], label_visibility="collapsed")
if file:
    gpx = gpxpy.parse(file)
    pts, d_acc = [], 0
    t_name = gpx.tracks[0].name if gpx.tracks and gpx.tracks[0].name else "Analyse"
    for track in gpx.tracks:
        for seg in track.segments:
            for i, p in enumerate(seg.points):
                d = p.distance_3d(seg.points[i-1]) if i > 0 else 0
                d_acc += d
                pts.append({'cum_dist': d_acc/1000, 'dist_diff': d, 'ele': p.elevation, 'lat': p.latitude, 'lon': p.longitude})
    
    df = pd.DataFrame(pts)
    total_w = u_weight + BIKE_WEIGHT + extra_load
    df['ele_diff'] = df['ele'].diff().fillna(0)
    df['v_ms'] = np.where(df['ele_diff'] > 0, 15/3.6, v_flat/3.6)
    df['dur'] = df['dist_diff'] / df['v_ms']
    
    sys_cap = m_wh + sum(e['wh'] for e in st.session_state.extenders)
    battery_stack = [{'cap': sys_cap, 'label': 'System'}] + [{'cap': s['wh'], 'label': f'Ersatz {i+1}'} for i, s in enumerate(st.session_state.spare_batteries)]
    
    active_c = sorted([dict(c) for c in st.session_state.charges], key=lambda x: x['km'])
    sorted_modes = sorted([dict(m) for m in st.session_state.modes], key=lambda x: x['km'])
    curr_idx, cons, last_p = 0, 0, 100.0
    pcts, events, markers, b_labels = [], [], [], []
    tf = 1.0 + (max(0, 20 - temp) * 0.008)

    for i in range(len(df)):
        km, v = df['cum_dist'].iloc[i], df['v_ms'].iloc[i]
        ev = None
        if active_c and km >= active_c[0]['km']:
            c = active_c.pop(0); cons = min(cons, battery_stack[curr_idx]['cap'] * (1 - c['pct']/100)); ev = 'charge'
        
        p_req = ((total_w * GRAVITY * df['ele_diff'].iloc[i].clip(min=0)) / max(df['dur'].iloc[i], 0.1)) + (total_w * GRAVITY * CRR * v) + (0.5 * AIR_DENSITY * v**3 * CW_AREA)
        m_curr = next((m['mode'] for m in reversed(sorted_modes) if km >= m['km']), list(spec['modes'].keys())[-1])
        # P_mot wird mit dem neutralen k_factor (1.0 +/- X) multipliziert
        p_mot = (p_req - min(p_req / (1 + spec['modes'][m_curr]), 150)) * k_factor
        e_seg = (((max(0.01, p_mot) * df['dur'].iloc[i] / 3600) / spec['efficiency']) * tf)
        cons += e_seg
        
        if cons >= battery_stack[curr_idx]['cap'] and curr_idx < len(battery_stack)-1:
            curr_idx += 1; cons, ev, last_p = 0, 'swap', 100.0
        
        p = max(0, ((battery_stack[curr_idx]['cap'] - cons) / battery_stack[curr_idx]['cap']) * 100)
        pcts.append(p); b_labels.append(battery_stack[curr_idx]['label'])
        if any(abs(m['km'] - km) < 0.05 for m in sorted_modes if m['km'] > 0): ev = 'mode_change' if not ev else ev
        events.append(ev); markers.append(next((t for t in [90,80,70,60,50,40,30,20,10,0] if last_p > t >= p), np.nan)); last_p = p

    df['battery_pct'], df['event'], df['marker'], df['batt_label'] = pcts, events, markers, b_labels
    df['color'] = np.select([df['battery_pct']>20, df['battery_pct']>10, df['battery_pct']>0], ['#00CC96', '#FFD700', '#FF4B4B'], default='#85144b')
    df['z_id'] = (df['color'] != df['color'].shift(1)).cumsum()

    st.markdown(f"### 🚩 {t_name}")
    c = st.columns(3)
    c[0].metric("Distanz", f"{df['cum_dist'].iloc[-1]:.1f} km")
    c[1].metric("Höhenmeter", f"{df['ele'].diff().clip(lower=0).sum():.0f} hm ↑")
    c[2].metric("Restakku", f"{df['battery_pct'].iloc[-1]:.1f} %")

    ansicht = st.radio("Ansicht:", ["Höhenprofil", "Karte"], horizontal=True, label_visibility="collapsed")
    if ansicht == "Höhenprofil":
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['cum_dist'], y=df['ele'], fill='tozeroy', fillcolor='rgba(100,100,100,0.1)', line=dict(width=0), hoverinfo='skip'))
        for zid in df['z_id'].unique():
            z_df = df[df['z_id'] == zid]
            fig.add_trace(go.Scatter(x=z_df['cum_dist'], y=z_df['ele'], mode='lines', line=dict(color=z_df['color'].iloc[-1], width=5), showlegend=False))
        m_pts = df[df['marker'].notnull()]
        fig.add_trace(go.Scatter(x=m_pts['cum_dist'], y=m_pts['ele']+20, mode='markers+text', text=[f"{int(v)}%" for v in m_pts['marker']], textfont=dict(color="white"), textposition="top center", marker=dict(color='white', size=4), showlegend=False))
        sw, ch, mc = df[df['event'] == 'swap'], df[df['event'] == 'charge'], df[df['event'] == 'mode_change']
        if not sw.empty: fig.add_trace(go.Scatter(x=sw['cum_dist'], y=sw['ele']+50, mode='markers', marker=dict(color='#2E91E5', size=12, symbol='square'), name="Wechsel"))
        if not ch.empty: fig.add_trace(go.Scatter(x=ch['cum_dist'], y=ch['ele']+50, mode='markers', marker=dict(color='#EF553B', size=12, symbol='star'), name="Laden"))
        if not mc.empty: fig.add_trace(go.Scatter(x=mc['cum_dist'], y=mc['ele']+50, mode='markers', marker=dict(color='#FECB52', size=10, symbol='hexagram'), name="Strategie"))
        st.plotly_chart(fig, use_container_width=True, key=f"plot_{v_flat}_{k_val}")
    else:
        m = folium.Map(location=[df['lat'].mean(), df['lon'].mean()], zoom_start=13)
        Fullscreen().add_to(m); df_map = df.iloc[::2]
        for zid in df_map['z_id'].unique():
            z_df = df_map[df_map['z_id'] == zid]
            folium.PolyLine(z_df[['lat', 'lon']].values.tolist(), color=z_df['color'].iloc[0], weight=6).add_to(m)
        for _, r in df[df['event'].notnull() | df['marker'].notnull()].iterrows():
            if r['event'] == 'charge': folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='orange', icon='bolt', prefix='fa')).add_to(m)
            elif r['event'] == 'swap': folium.Marker([r['lat'], r['lon']], icon=folium.Icon(color='blue', icon='refresh', prefix='fa')).add_to(m)
            elif not np.isnan(r['marker']): folium.Marker([r['lat'], r['lon']], icon=folium.DivIcon(html=f'<div style="font-size: 10pt; font-weight: bold; color: white; background: rgba(0,0,0,0.6); padding: 2px 4px; border-radius: 4px; border: 1px solid white; white-space:nowrap;">{int(r["marker"])}%</div>')).add_to(m)
        folium_static(m, width=1200, height=750)
