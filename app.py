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

# --- KONFIGURATION & DATEN ---
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
        u_weight = c1.number_input("Fahrer Kg", 50, 150, 95)
        extra_load = c2.number_input("Last Kg", 0, 30, 5)
        temp = st.slider("Temp °C", -10, 35, 12)
        v_flat = st.slider("Ø km/h Ebene", 10, 45, 25)

    with st.expander("🔋 Akkus", expanded=True):
        m_wh = st.number_input("Hauptakku Wh", 200, 1000, spec['default_cap'], step=10)
        st.divider()
        h1, h2 = st.columns([3, 1]); h1.markdown("**+ Extender**")
        if h2.button("➕", key="add_ex"): st.session_state.extenders.append({'wh': 250}); st.rerun()
        for i, ext in enumerate(st.session_state.extenders):
            col1, col2 = st.columns([4, 1])
            st.session_state.extenders[i]['wh'] = col1.number_input("Wh", 50, 500, ext['wh'], key=f"ex_{i}", label_visibility="collapsed")
            if col2.button("🗑️", key=f"dex_{i}"): st.session_state.extenders.pop(i); st.rerun()
        st.divider()
        h3, h4 = st.columns([3, 1]); h3.markdown("**+ Ersatz**")
        if h4.button("➕", key="add_sp"): st.session_state.spare_batteries.append({'wh': spec['default_cap']}); st.rerun()
        for i, sp in enumerate(st.session_state.spare_batteries):
            col1, col2 = st.columns([4, 1])
            st.session_state.spare_batteries[i]['wh'] = col1.number_input("Wh", 200, 1000, sp['wh'], key=f"sp_{i}", label_visibility="collapsed")
            if col2.button("🗑️", key=f"dsp_{i}"): st.session_state.spare_batteries.pop(i); st.rerun()

    with st.expander("⚡ Strategie"):
        if st.button("➕ Wechsel", use_container_width=True): 
            st.session_state.modes.append({'id': time.time(), 'km': 10, 'mode': list(spec['modes'].keys())[0]}); st.rerun()
        for i, m in enumerate(st.session_state.modes):
            mc1, mc2, mc3 = st.columns([1.2, 2.5, 0.8])
            st.session_state.modes[i]['km'] = mc1.number_input("km", 0, 250, m['km'], key=f"mkm_{i}", label_visibility="collapsed", disabled=(i==0))
            st.session_state.modes[i]['mode'] = mc2.selectbox("Mod", list(spec['modes'].keys()), key=f"mtyp_{i}", label_visibility="collapsed", index=list(spec['modes'].keys()).index(m['mode']))
            if i > 0 and mc3.button("🗑️", key=f"mdel_{i}"): st.session_state.modes.pop(i); st.rerun()

    with st.expander("☕ Ladestopps"):
        if st.button("➕ Laden", use_container_width=True): 
            st.session_state.charges.append({'id': time.time(), 'km': 30, 'pct': 80}); st.rerun()
        for i, c in enumerate(st.session_state.charges):
            lc1, lc2, lc3 = st.columns([1.5, 1.5, 0.8])
            st.session_state.charges[i]['km'] = lc1.number_input("km", 0, 250, c['km'], key=f"ckm_{i}", label_visibility="collapsed")
            st.session_state.charges[i]['pct'] = lc2.number_input("%", 1, 100, c['pct'], key=f"cpct_{i}", label_visibility="collapsed")
            if lc3.button("🗑️", key=f"cdel_{i}"): st.session_state.charges.pop(i); st.rerun()

# --- RECHNERKERN ---
def run_calc(points, weight, temp, speed_flat, motor_name, main_cap_val):
    df = pd.DataFrame(points)
    m_spec = MOTOR_SYSTEMS[motor_name]
    df['ele_diff'] = df['ele'].diff().fillna(0)
    df['dist_diff'] = df['dist_diff'].fillna(0)
    
    # Der Slider v_flat beeinflusst hier direkt die v_ms
    df['v_ms'] = np.where(df['ele_diff'] > 0, 12/3.6, speed_flat/3.6)
    df['dur'] = df['dist_diff'] / df['v_ms']
    
    sys_cap = main_cap_val + sum(e['wh'] for e in st.session_state.extenders)
    battery_stack = [{'cap': sys_cap, 'label': 'System'}] + [{'cap': s['wh'], 'label': f'Ersatz {i+1}'} for i, s in enumerate(st.session_state.spare_batteries)]
    
    curr_idx, cons, last_p = 0, 0, 100.0
    pcts, events, markers, labels = [], [], [], []
    active_c = sorted([dict(c) for c in st.session_state.charges], key=lambda x: x['km'])
    sorted_modes = sorted([dict(m) for m in st.session_state.modes], key=lambda x: x['km'])
    tf = 1.0 + (max(0, 20 - temp) * 0.008)

    for i in range(len(df)):
        km, v = df['cum_dist'].iloc[i], df['v_ms'].iloc[i]
        ev = None
        
        if active_c and km >= active_c[0]['km']:
            c = active_c.pop(0)
            target = battery_stack[curr_idx]['cap'] * (1 - c['pct']/100)
            if cons > target: cons = target
            ev = 'charge'
        
        if any(abs(m['km'] - km) < 0.05 for m in sorted_modes if m['km'] > 0):
            ev = 'mode_change' if not ev else ev

        # Physik (Leistung)
        p_air = 0.5 * AIR_DENSITY * (v**3) * CW_AREA
        p_roll = weight * GRAVITY * CRR_FOREST * v
        p_slope = (weight * GRAVITY * df['ele_diff'].iloc[i].clip(min=0)) / max(df['dur'].iloc[i], 0.1)
        p_req = p_slope + p_roll + p_air
        
        m_curr = next((m['mode'] for m in reversed(sorted_modes) if km >= m['km']), list(m_spec['modes'].keys())[-1])
        p_mot = p_req - min(p_req / (1 + m_spec['modes'][m_curr]), 150)
        
        e_seg = (m_spec['drag_factor'] * (df['dist_diff'].iloc[i]/1000)) if df['ele_diff'].iloc[i] <= 0 else (((max(0, p_mot) * df['dur'].iloc[i] / 3600) / m_spec['efficiency']) * tf)
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
    df = run_calc(st.session_state.points_data, u_weight+BIKE_WEIGHT+extra_load, temp, v_flat, sel_motor, m_wh)
    
    st.markdown(f"### 🚩 Tour Analyse")
    cols = st.columns(4)
    cols[0].metric("Distanz", f"{df['cum_dist'].iloc[-1]:.1f} km")
    cols[1].metric("Höhenmeter", f"{df['ele'].diff().clip(lower=0).sum():.0f} hm ↑")
    cols[2].metric("Restakku", f"{df['battery_pct'].iloc[-1]:.1f} %")
    cols[3].metric("Aktiv", df['batt_label'].iloc[-1])

    view_option = st.radio("Ansicht:", ["Höhenprofil", "Karte"], horizontal=True)
    
    if view_option == "Höhenprofil":
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['cum_dist'], y=df['ele'], fill='tozeroy', fillcolor='rgba(100,100,100,0.1)', line=dict(width=0), hoverinfo='skip'))
        for zid in df['z_id'].unique():
            z_df = df[df['z_id'] == zid]
            fig.add_trace(go.Scatter(x=z_df['cum_dist'], y=z_df['ele'], mode='lines', line=dict(color=z_df['color'].iloc[-1], width=5), showlegend=False))
        
        m_df = df[df['marker'].notnull()]
        if not m_df.empty:
            fig.add_trace(go.Scatter(x=m_df['cum_dist'], y=m_df['ele']+20, mode='markers+text', text=[f"{int(v)}%" for v in m_df['marker']], textfont=dict(color="white"), textposition="top center", marker=dict(color='white', size=4), showlegend=False))
        
        sw_df, ch_df, st_df = df[df['event'] == 'swap'], df[df['event'] == 'charge'], df[df['event'] == 'mode_change']
        if not sw_df.empty: fig.add_trace(go.Scatter(x=sw_df['cum_dist'], y=sw_df['ele']+50, mode='markers', marker=dict(color='#2E91E5', size=12, symbol='square'), name="Wechsel"))
        if not ch_df.empty: fig.add_trace(go.Scatter(x=ch_df['cum_dist'], y=ch_df['ele']+50, mode='markers', marker=dict(color='#EF553B', size=12, symbol='star'), name="Laden"))
        if not st_df.empty: fig.add_trace(go.Scatter(x=st_df['cum_dist'], y=st_df['ele']+50, mode='markers', marker=dict(color='#FECB52', size=10, symbol='hexagram'), name="Strategie"))
        
        fig.update_layout(height=600, margin=dict(l=10, r=10, t=10, b=10))
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
            elif not np.isnan(row['marker']): folium.Marker(loc, icon=folium.DivIcon(html=f'<div style="font-size: 10pt; font-weight: bold; color: white; background: rgba(0,0,0,0.6); padding: 2px 4px; border-radius: 4px; border: 1px solid white; white-space:nowrap;">{int(row["marker"])}%</div>')).add_to(m)
        folium_static(m, width=1200, height=750)
