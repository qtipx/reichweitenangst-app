import streamlit as st
import gpxpy
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
import os

# --- KALIBRIERTE PHYSIKALISCHE KONSTANTEN ---
BIKE_WEIGHT, GRAVITY, AIR_DENSITY = 26.0, 9.81, 1.225
CW_AREA, EFFICIENCY, CRR_FOREST = 0.72, 0.78, 0.045 
BOSCH_MODES = {"Eco": 0.60, "Tour": 1.40, "PWR/eMTB": 2.50, "Turbo": 3.40}

st.set_page_config(page_title="Reichweitenangst", layout="wide")

# --- INITIALISIERUNG ---
if 'charges' not in st.session_state: st.session_state.charges = []
if 'modes' not in st.session_state: st.session_state.modes = [{'id': 1, 'km': 0, 'mode': 'Turbo'}]
if 'points_data' not in st.session_state: st.session_state.points_data = None

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("reichweitenangst.png"):
        st.image("reichweitenangst.png", use_container_width=True)
    st.markdown("<h2 style='text-align: center; color: #F7D106; font-size: 24px; font-weight: 900; margin: 0;'>REICHWEITENANGST</h2>", unsafe_allow_html=True)
    
    with st.expander("👤 Setup", expanded=True):
        c1, c2 = st.columns(2)
        u_weight = c1.number_input("Fahrer Kg", 50, 150, 95)
        extra_load = c2.number_input("Last Kg", 0, 30, 5)
        rider_type = st.select_slider("Fitness", options=["Gering", "Mittel", "Sportlich"], value="Mittel")
        temp = st.slider("Temp °C", -10, 35, 12)
        avg_speed_flat = st.slider("Ø km/h Ebene", 20, 45, 28)

    with st.expander("🔋 Akkus", expanded=True):
        main_cap = 625
        has_extender = st.checkbox("Extender (+500Wh)")
        ext_cap = 500 if has_extender else 0
        spare1 = st.checkbox("Ersatz 1 (625Wh)")
        spare2 = st.checkbox("Ersatz 2 (500Wh)")

    with st.expander("⚡ Modi", expanded=True):
        for idx, m in enumerate(st.session_state.modes):
            mc1, mc2, mc3 = st.columns([1.2, 2.5, 0.8])
            st.session_state.modes[idx]['km'] = mc1.number_input("km", 0, 200, m['km'], key=f"mkm_{m['id']}", label_visibility="collapsed")
            st.session_state.modes[idx]['mode'] = mc2.selectbox("Mod", list(BOSCH_MODES.keys()), index=list(BOSCH_MODES.keys()).index(m['mode']), key=f"mtyp_{m['id']}", label_visibility="collapsed")
            if mc3.button("🗑️", key=f"mdel_{m['id']}"):
                st.session_state.modes.pop(idx)
                st.rerun()
        if st.button("➕ Modus", use_container_width=True):
            st.session_state.modes.append({'id': int(time.time()*1000), 'km': 20, 'mode': 'Tour'})
            st.rerun()

    with st.expander("☕ Ladestopps"):
        for idx, c in enumerate(st.session_state.charges):
            l1, l2, l3 = st.columns([1.5, 1.5, 0.8])
            st.session_state.charges[idx]['km'] = l1.number_input("km", 0, 150, c['km'], key=f"ckm_{c['id']}", label_visibility="collapsed")
            st.session_state.charges[idx]['pct'] = l2.number_input("%", 1, 100, c['pct'], key=f"cpct_{c['id']}", label_visibility="collapsed")
            if l3.button("🗑️", key=f"cdel_{c['id']}"):
                st.session_state.charges.pop(idx)
                st.rerun()
        if st.button("➕ Stop", use_container_width=True):
            st.session_state.charges.append({'id': int(time.time()*1000), 'km': 30, 'pct': 80})
            st.rerun()

# --- HAUPTFENSTER ---
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

# --- RECHNERKERN ---
def run_calc(points, weight, fitness, temp, charges, modes):
    df = pd.DataFrame(points)
    base_w = {"Gering": 85, "Mittel": 125, "Sportlich": 170}[fitness]
    df['ele_diff'], df['dist_diff'] = df['ele'].diff().fillna(0), df['dist_diff'].fillna(0)
    df['v_ms'] = np.where(df['ele_diff'] > 0, 12/3.6, avg_speed_flat/3.6)
    df['dur'] = np.where(df['v_ms'] > 0, df['dist_diff'] / df['v_ms'], 0.1)
    
    battery_stack = [{'cap': main_cap + ext_cap, 'label': 'System'}]
    if spare1: battery_stack.append({'cap': 625 + ext_cap, 'label': 'Ersatz 1'})
    if spare2: battery_stack.append({'cap': 500 + ext_cap, 'label': 'Ersatz 2'})
    
    curr_batt_idx, cons_in_curr, last_p = 0, 0, 100.0
    pcts, events, labels, markers = [], [], [], []
    active_c = sorted([dict(c) for c in charges], key=lambda x: x['km'])
    sorted_modes = sorted(modes, key=lambda x: x['km'], reverse=True)
    tf = 1.0 + (max(0, 20 - temp) * 0.008)

    for i in range(len(df)):
        km = df['cum_dist'].iloc[i]
        is_charge = False
        
        if active_c and km >= active_c[0]['km']:
            c = active_c.pop(0)
            target = battery_stack[curr_batt_idx]['cap'] * (1 - c['pct']/100)
            if cons_in_curr > target: cons_in_curr = target
            is_charge = True

        p_req = ((weight * 9.81 * df['ele_diff'].iloc[i].clip(min=0)) / df['dur'].iloc[i]) + \
                (weight * 9.81 * CRR_FOREST * df['v_ms'].iloc[i]) + (0.5 * AIR_DENSITY * df['v_ms'].iloc[i]**3 * CW_AREA)
        
        m_curr = next((m['mode'] for m in sorted_modes if km >= m['km']), modes[0]['mode'])
        support = BOSCH_MODES[m_curr]
        
        if df['ele_diff'].iloc[i] <= 0:
            e_seg = 0.7 * (df['dist_diff'].iloc[i] / 1000)
        else:
            p_motor = p_req - min(p_req / (1 + support), base_w * 1.5)
            e_seg = ((max(0, p_motor) * df['dur'].iloc[i] / 3600) / EFFICIENCY) * tf
            
        cons_in_curr += e_seg
        is_swap = False
        if cons_in_curr >= battery_stack[curr_batt_idx]['cap'] and curr_batt_idx < len(battery_stack) - 1:
            curr_batt_idx += 1
            cons_in_curr, is_swap, last_p = 0, True, 100.0
            
        p = max(0, ((battery_stack[curr_batt_idx]['cap'] - cons_in_curr) / battery_stack[curr_batt_idx]['cap']) * 100)
        pcts.append(p)
        labels.append(battery_stack[curr_batt_idx]['label'])
        
        # Event & Marker Logik
        ev = None
        if is_charge: ev = 'charge'
        if is_swap: ev = 'swap'
        events.append(ev)
        
        m = next((t for t in [90, 80, 70, 60, 50, 40, 30, 20, 10, 0] if last_p > t >= p), None)
        markers.append(m)
        last_p = p

    df['battery_pct'], df['event'], df['batt_name'], df['marker'] = pcts, events, labels, markers
    return df

# --- UI ---
if st.session_state.points_data:
    df = run_calc(st.session_state.points_data, u_weight+BIKE_WEIGHT+extra_load, rider_type, temp, st.session_state.charges, st.session_state.modes)
    
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("km", f"{df['cum_dist'].iloc[-1]:.1f}")
    m2.metric("hm ↑", f"{df['ele'].diff().clip(lower=0).sum():.0f}")
    m3.metric("Akku %", f"{df['battery_pct'].iloc[-1]:.1f}")
    m4.metric("Aktiv", df['batt_name'].iloc[-1])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['cum_dist'], y=df['ele'], fill='tozeroy', line=dict(width=0), fillcolor='rgba(100,100,100,0.1)', hoverinfo='skip'))
    
    # Linie
    df['color'] = np.select([df['battery_pct']>20, df['battery_pct']>10, df['battery_pct']>0], ['#00CC96', '#FFD700', '#FF851B'], default='#85144b')
    df['z_id'] = (df['color'] != df['color'].shift(1)).cumsum()
    for zid in df['z_id'].unique():
        z_df = df[df['z_id'] == zid]
        if zid > 1: z_df = pd.concat([df[df['z_id'] == zid-1].iloc[[-1]], z_df])
        fig.add_trace(go.Scatter(x=z_df['cum_dist'], y=z_df['ele'], mode='lines', line=dict(color=z_df['color'].iloc[-1], width=5), showlegend=False))
    
    # %-Marker
    m_pts = df[df['marker'].notnull()]
    if not m_pts.empty:
        fig.add_trace(go.Scatter(x=m_pts['cum_dist'], y=m_pts['ele'], mode='markers+text', text=[f"{int(m)}%" for m in m_pts['marker']], textfont=dict(size=9), textposition="top center", marker=dict(color='white', size=4)))

    # Ladestopps (Gelber Stern)
    c_pts = df[df['event'] == 'charge']
    if not c_pts.empty:
        fig.add_trace(go.Scatter(x=c_pts['cum_dist'], y=c_pts['ele'], mode='markers', marker=dict(color='#F7D106', size=20, symbol='star'), name="Ladestopp"))

    # Akkuwechsel (Weißer Stern)
    s_pts = df[df['event'] == 'swap']
    if not s_pts.empty:
        fig.add_trace(go.Scatter(x=s_pts['cum_dist'], y=s_pts['ele'], mode='markers+text', text="🔄 WECHSEL", textfont=dict(color="white", size=10), textposition="top center", marker=dict(color='white', size=20, symbol='star'), name="Wechsel"))

    fig.update_layout(xaxis_title="km", yaxis_title="m", template="plotly_dark", height=500, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)