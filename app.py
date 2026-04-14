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

# --- VOLLSTÄNDIGE DATENBANK (18 MOTOREN) ---
MOTOR_SYSTEMS = {
    "Bosch Smart System (Gen4)": {"modes": {"Eco": 0.6, "Tour+": 1.4, "eMTB": 2.5, "Turbo": 3.4}, "efficiency": 0.80, "drag_factor": 0.6, "default_cap": 750},
    "Bosch CX (Gen4 Old)": {"modes": {"Eco": 0.6, "Tour": 1.4, "eMTB": 2.5, "Turbo": 3.4}, "efficiency": 0.79, "drag_factor": 0.6, "default_cap": 625},
    "Bosch CX (Gen2 - Ritzel)": {"modes": {"Eco": 0.5, "Tour": 1.2, "Sport": 2.1, "Turbo": 3.0}, "efficiency": 0.74, "drag_factor": 1.2, "default_cap": 500},
    "Bosch Performance Line SX": {"modes": {"Eco": 0.6, "Tour+": 1.2, "Sprint": 2.8, "Turbo": 3.4}, "efficiency": 0.82, "drag_factor": 0.3, "default_cap": 400},
    "DJI Avinox (M1/M2)": {"modes": {"Eco": 1.0, "Auto": 2.5, "Trail": 4.5, "Turbo": 7.0, "Boost": 8.0}, "efficiency": 0.83, "drag_factor": 0.3, "default_cap": 800},
    "Pinion MGU (E1.12)": {"modes": {"Eco": 0.8, "Flow": 1.6, "Flex": 2.8, "Fly": 4.0}, "efficiency": 0.77, "drag_factor": 0.8, "default_cap": 800},
    "Specialized / Brose Mag S": {"modes": {"Eco": 0.35, "Trail": 1.0, "Turbo": 4.1}, "efficiency": 0.82, "drag_factor": 0.2, "default_cap": 700},
    "Specialized SL 1.1 / 1.2": {"modes": {"Eco": 0.35, "Trail": 1.0, "Turbo": 2.0}, "efficiency": 0.84, "drag_factor": 0.1, "default_cap": 320},
    "Shimano EP801": {"modes": {"Eco": 0.6, "Trail": 1.5, "Boost": 3.5}, "efficiency": 0.79, "drag_factor": 0.5, "default_cap": 630},
    "Shimano EP8 (RS)": {"modes": {"Eco": 0.5, "Trail": 1.2, "Boost": 3.0}, "efficiency": 0.80, "drag_factor": 0.4, "default_cap": 540},
    "Shimano E8000": {"modes": {"Eco": 0.5, "Trail": 1.1, "Boost": 3.0}, "efficiency": 0.75, "drag_factor": 0.9, "default_cap": 504},
    "Yamaha PW-X3": {"modes": {"+Eco": 0.5, "Eco": 1.0, "Std": 1.9, "High": 2.8, "EXPW": 3.6}, "efficiency": 0.79, "drag_factor": 0.6, "default_cap": 720},
    "Yamaha PW-ST": {"modes": {"+Eco": 0.5, "Eco": 1.0, "Std": 1.9, "High": 2.8}, "efficiency": 0.77, "drag_factor": 0.7, "default_cap": 630},
    "Fazua Ride 60": {"modes": {"Breeze": 0.6, "River": 1.5, "Rocket": 3.5}, "efficiency": 0.81, "drag_factor": 0.2, "default_cap": 430},
    "Fazua Evation 50": {"modes": {"Breeze": 0.5, "River": 1.2, "Rocket": 2.5}, "efficiency": 0.78, "drag_factor": 0.4, "default_cap": 252},
    "TQ HPR50": {"modes": {"Eco": 0.5, "Mid": 1.2, "High": 2.0}, "efficiency": 0.80, "drag_factor": 0.1, "default_cap": 360},
    "Rocky Mountain Dyname 4.0": {"modes": {"Eco": 0.5, "Trail": 1.5, "Ludicrous": 3.5}, "efficiency": 0.76, "drag_factor": 1.0, "default_cap": 720},
    "Bafang M510 / M620": {"modes": {"1": 0.5, "2": 1.2, "3": 2.2, "4": 3.5, "5": 5.0}, "efficiency": 0.72, "drag_factor": 1.1, "default_cap": 840}
}

GRAVITY, AIR_DENSITY, CW_AREA, CRR_FOREST = 9.81, 1.225, 0.72, 0.045 
 
st.set_page_config(page_title="Reichweitenangst", layout="wide")

if 'points_data' not in st.session_state: st.session_state.points_data = None
for key in ['charges', 'modes', 'extenders', 'spare_batteries']:
    if key not in st.session_state: st.session_state[key] = []

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("reichweitenangst.png"): st.image("reichweitenangst.png", use_container_width=True)
    st.markdown("<h2 style='text-align: center; color: #F7D106; margin-bottom: 0px;'>REICHWEITENANGST</h2>", unsafe_allow_html=True)
    st.markdown("""
    <div style='text-align: center; margin-top: -5px; margin-bottom: 20px;'>
        <p style='font-size: 0.8em; color: #aaa;'>
            By Markus Lissner | <a href='mailto:m@lissner.de' style='color: #F7D106; text-decoration: none;'>m@lissner.de</a>
        </p>
    </div>
    """, unsafe_allow_html=True)

    sel_motor = st.selectbox("Motor", list(MOTOR_SYSTEMS.keys()), index=0)
    spec = MOTOR_SYSTEMS[sel_motor]
    
    if not st.session_state.modes:
        st.session_state.modes = [{'id': 1, 'km': 0, 'mode': list(spec['modes'].keys())[-1]}]

    with st.expander("👤 Setup", expanded=True):
        u_weight = st.number_input("Fahrer Kg", 50, 150, 95)
        bike_weight = st.number_input("Fahrrad Kg", 10.0, 35.0, 24.5, step=0.5)
        extra_load = st.number_input("Last Kg", 0, 30, 5)
        st.divider()
        corr_factor = st.slider("Korrekturfaktor (Wind/Boden)", -1.0, 1.0, 0.0, 0.1)
        temp = st.slider("Temp °C", -10, 35, 12)
        v_flat = st.slider("Ø km/h Ebene", 15, 45, 25)

    with st.expander("🔋 Akkus", expanded=True):
        m_wh = st.number_input("Hauptakku Wh", 200, 1000, spec['default_cap'], step=10)
        if st.button("➕ Extender"): st.session_state.extenders.append({'wh': 250}); st.rerun()
        for i, ext in enumerate(st.session_state.extenders):
            c1, c2 = st.columns([4, 1])
            st.session_state.extenders[i]['wh'] = c1.number_input(f"Ex {i+1} Wh", 50, 500, ext['wh'], key=f"ex_{i}")
            if c2.button("🗑️", key=f"dex_{i}"): st.session_state.extenders.pop(i); st.rerun()
        if st.button("➕ Ersatzakku"): st.session_state.spare_batteries.append({'wh': spec['default_cap']}); st.rerun()
        for i, sp in enumerate(st.session_state.spare_batteries):
            c1, c2 = st.columns([4, 1])
            st.session_state.spare_batteries[i]['wh'] = c1.number_input(f"Sp {i+1} Wh", 200, 1000, sp['wh'], key=f"sp_{i}")
            if c2.button("🗑️", key=f"dsp_{i}"): st.session_state.spare_batteries.pop(i); st.rerun()

    with st.expander("⚡ Strategie"):
        if st.button("➕ Wechsel"): st.session_state.modes.append({'id': time.time(), 'km': 10, 'mode': list(spec['modes'].keys())[0]}); st.rerun()
        for i, m in enumerate(st.session_state.modes):
            mc1, mc2, mc3 = st.columns([1.2, 2.5, 0.8])
            st.session_state.modes[i]['km'] = mc1.number_input("km", 0, 250, m['km'], key=f"mkm_{i}", disabled=(i==0))
            st.session_state.modes[i]['mode'] = mc2.selectbox("Mod", list(spec['modes'].keys()), key=f"mtyp_{i}", index=list(spec['modes'].keys()).index(m['mode']))
            if i > 0 and mc3.button("🗑️", key=f"mdel_{i}"): st.session_state.modes.pop(i); st.rerun()

    with st.expander("☕ Ladestopps"):
        if st.button("➕ Laden"): st.session_state.charges.append({'id': time.time(), 'km': 30, 'pct': 80}); st.rerun()
        for i, c in enumerate(st.session_state.charges):
            lc1, lc2, lc3 = st.columns([1.5, 1.5, 0.8])
            st.session_state.charges[i]['km'] = lc1.number_input("km", 0, 250, c['km'], key=f"ckm_{i}")
            st.session_state.charges[i]['pct'] = lc2.number_input("%", 1, 100, c['pct'], key=f"cpct_{i}")
            if lc3.button("🗑️", key=f"cdel_{i}"): st.session_state.charges.pop(i); st.rerun()

# --- RECHNERKERN ---
def run_calc(points, total_weight, temp, corr, motor_name):
    df = pd.DataFrame(points)
    m_spec = MOTOR_SYSTEMS[motor_name]
    df['ele_diff'], df['dist_diff'] = df['ele'].diff().fillna(0), df['dist_diff'].fillna(0)
    df['v_ms'] = np.where(df['ele_diff'] > 0, 12/3.6, v_flat/3.6)
    df['dur'] = np.where(df['v_ms'] > 0, df['dist_diff'] / df['v_ms'], 0.1)
    
    main_cap = m_wh + sum(e['wh'] for e in st.session_state.extenders)
    battery_stack = [{'cap': main_cap, 'label': 'System'}] + [{'cap': s['wh'], 'label': f'Ersatz {i+1}'} for i, s in enumerate(st.session_state.spare_batteries)]
    
    curr_idx, cons, last_p = 0, 0, 100.0
    pcts, events, markers, labels = [], [], [], []
    active_c = sorted([dict(c) for c in st.session_state.charges], key=lambda x: x['km'])
    sorted_modes = sorted([dict(m) for m in st.session_state.modes], key=lambda x: x['km'])
    
    tf = 1.0 + (max(0, 20 - temp) * 0.008)
    eff_corr = m_spec['efficiency'] * (1.0 + (corr * 0.1))

    for i in range(len(df)):
        km, ele_d = df['cum_dist'].iloc[i], df['ele_diff'].iloc[i]
        ev = None
        if active_c and km >= active_c[0]['km']:
            c = active_c.pop(0); target = battery_stack[curr_idx]['cap'] * (1 - c['pct']/100)
            if cons > target: cons = target
            ev = 'charge'
        if any(abs(m['km'] - km) < 0.05 for m in sorted_modes if m['km'] > 0): ev = 'mode_change' if not ev else ev

        p_slope = total_weight * GRAVITY * (ele_d / df['dur'].iloc[i])
        p_resist = (total_weight * GRAVITY * CRR_FOREST * df['v_ms'].iloc[i]) + (0.5 * AIR_DENSITY * df['v_ms'].iloc[i]**3 * CW_AREA)
        p_req = p_slope + p_resist
        m_curr = next((m['mode'] for m in reversed(sorted_modes) if km >= m['km']), list(m_spec['modes'].keys())[-1])
        base_drag = m_spec['drag_factor'] * (df['dist_diff'].iloc[i]/1000)

        if ele_d > 0: # Bergauf
            p_mot = p_req - min(p_req / (1 + m_spec['modes'][m_curr]), 125 * 1.5)
            e_seg = (((max(0, p_mot) * df['dur'].iloc[i] / 3600) / eff_corr) + base_drag) * tf
        elif ele_d < -0.1: # Bergab: Verbrauch auf Null/Systemlast
            e_seg = base_drag * 0.05 
        else: # Ebene
            p_mot = max(0, p_resist - (p_resist / (1 + m_spec['modes'][m_curr])))
            e_seg = ((p_mot * df['dur'].iloc[i] / 3600) / eff_corr + base_drag) * tf
        
        cons += e_seg
        if cons >= battery_stack[curr_idx]['cap'] and curr_idx < len(battery_stack) - 1:
            curr_idx += 1; cons, ev, last_p = 0, 'swap', 100.0
        p = max(0, ((battery_stack[curr_idx]['cap'] - cons) / battery_stack[curr_idx]['cap']) * 100)
        pcts.append(p); events.append(ev); labels.append(battery_stack[curr_idx]['label'])
        m_val = next((t for t in [90, 80, 70, 60, 50, 40, 30, 20, 10, 0] if last_p > t >= p), np.nan)
        markers.append(m_val); last_p = p

    df['battery_pct'], df['event'], df['marker'], df['batt_label'] = pcts, events, markers, labels
    df['color'] = np.select([df['battery_pct']>20, df['battery_pct']>10, df['battery_pct']>0], ['#00CC96', '#FFD700', '#FF4B4B'], default='#85144b')
    df['z_id'] = (df['color'] != df['color'].shift(1)).cumsum()
    return df

# --- MAIN UI ---
file = st.file_uploader("GPX laden", type=["gpx"])
if file:
    gpx = gpxpy.parse(file)
    st.session_state.tour_name = gpx.tracks[0].name if gpx.tracks and gpx.tracks[0].name else file.name
    pts, d_acc = [], 0
    for track in gpx.tracks:
        for seg in track.segments:
            for i, p in enumerate(seg.points):
                d = p.distance_3d(seg.points[i-1]) if i > 0 else 0
                d_acc += d
                pts.append({'cum_dist': d_acc/1000, 'dist_diff': d, 'ele': p.elevation, 'lat': p.latitude, 'lon': p.longitude})
    st.session_state.points_data = pts

if st.session_state.points_data:
    df = run_calc(st.session_state.points_data, u_weight + extra_load + bike_weight, temp, corr_factor, sel_motor)
    
    st.markdown(f"### 🚩 {st.session_state.tour_name}")
    st.write(f"**Tour-Analyse:** {df['cum_dist'].iloc[-1]:.1f} km | {df['ele'].diff().clip(lower=0).sum():.0f} hm ↑")
    
    cols = st.columns(4)
    cols[0].metric("Distanz", f"{df['cum_dist'].iloc[-1]:.1f} km")
    cols[1].metric("Höhenmeter", f"{df['ele'].diff().clip(lower=0).sum():.0f} hm ↑")
    cols[2].metric("Restakku", f"{df['battery_pct'].iloc[-1]:.1f} %")
    cols[3].metric("Aktiv", df['batt_label'].iloc[-1])

    view = st.radio("Ansicht:", ["Höhenprofil", "Karte"], horizontal=True, label_visibility="collapsed")
    if view == "Höhenprofil":
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['cum_dist'], y=df['ele'], fill='tozeroy', fillcolor='rgba(100,100,100,0.1)', line=dict(width=0), hoverinfo='skip', showlegend=False))
        for zid in df['z_id'].unique():
            z_df = df[df['z_id'] == zid]
            fig.add_trace(go.Scatter(x=z_df['cum_dist'], y=z_df['ele'], mode='lines', line=dict(color=z_df['color'].iloc[-1], width=5), showlegend=False))
        
        m_df = df[df['marker'].notnull()]
        if not m_df.empty:
            fig.add_trace(go.Scatter(x=m_df['cum_dist'], y=m_df['ele']+30, mode='markers+text', text=[f"{int(v)}%" for v in m_df['marker']], textfont=dict(color="white"), textposition="top center", marker=dict(color='white', size=4), name="Akku %"))
        
        for ev_type, color, symbol, name in [('swap', '#2E91E5', 'square', 'Wechsel'), ('charge', '#EF553B', 'star', 'Laden'), ('mode_change', '#FECB52', 'hexagram', 'Strategie')]:
            ev_df = df[df['event'] == ev_type]
            if not ev_df.empty:
                fig.add_trace(go.Scatter(x=ev_df['cum_dist'], y=ev_df['ele']+60, mode='markers', marker=dict(color=color, size=12, symbol=symbol), name=name))
        
        fig.update_layout(height=650, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
        st.plotly_chart(fig, use_container_width=True)
    else:
        m = folium.Map(location=[df['lat'].mean(), df['lon'].mean()], zoom_start=13, tiles="OpenStreetMap")
        Fullscreen().add_to(m)
        df_map = df.iloc[::2]
        for zid in df_map['z_id'].unique():
            z_df = df_map[df_map['z_id'] == zid]
            folium.PolyLine(z_df[['lat', 'lon']].values.tolist(), color=z_df['color'].iloc[0], weight=6, opacity=0.8).add_to(m)
        for _, row in df[df['event'].notnull() | df['marker'].notnull()].iterrows():
            loc = [row['lat'], row['lon']]
            if row['event'] == 'charge': folium.Marker(loc, icon=folium.Icon(color='orange', icon='bolt', prefix='fa')).add_to(m)
            elif row['event'] == 'swap': folium.Marker(loc, icon=folium.Icon(color='blue', icon='refresh', prefix='fa')).add_to(m)
            elif not np.isnan(row['marker']): folium.Marker(loc, icon=folium.DivIcon(html=f'<div style="font-size:10pt;color:white;background:rgba(0,0,0,0.6);padding:2px 4px;border:1px solid white;white-space:nowrap;">{int(row["marker"])}%</div>')).add_to(m)
        folium_static(m, width=1200, height=750)
