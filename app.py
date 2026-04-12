import streamlit as st
import gpxpy
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
import os

# --- GLOBALE MOTOREN-DATENBANK ---
# support: Max Multiplikator (1.0 = 100%)
# efficiency: Wirkungsgrad (0.7 - 0.85)
# drag_factor: Widerstand in Wh/km (Leerlauf/Abfahrt)
MOTOR_SYSTEMS = {
    "DJI Avinox (M1/M2)": {
        "modes": {"Eco": 1.00, "Auto": 2.50, "Trail": 4.50, "Turbo": 7.00, "Boost": 8.00},
        "efficiency": 0.83, "drag_factor": 0.3, "default_cap": 800
    },
    "Bosch Smart System (Gen4)": {
        "modes": {"Eco": 0.60, "Tour+": 1.40, "eMTB": 2.50, "Turbo": 3.40},
        "efficiency": 0.80, "drag_factor": 0.6, "default_cap": 750
    },
    "Pinion MGU (E1.12)": {
        "modes": {"Eco": 0.80, "Flow": 1.60, "Flex": 2.80, "Fly": 4.00},
        "efficiency": 0.77, "drag_factor": 0.8, "default_cap": 800
    },
    "Specialized / Brose Mag S": {
        "modes": {"Eco": 0.35, "Trail": 1.00, "Turbo": 4.10},
        "efficiency": 0.82, "drag_factor": 0.2, "default_cap": 700
    },
    "Shimano EP801 / EP8": {
        "modes": {"Eco": 0.60, "Trail": 1.50, "Boost": 3.50},
        "efficiency": 0.78, "drag_factor": 0.5, "default_cap": 630
    },
    "Bosch CX (Gen2 - kl. Ritzel)": {
        "modes": {"Eco": 0.50, "Tour": 1.20, "Sport": 2.10, "Turbo": 3.00},
        "efficiency": 0.74, "drag_factor": 1.2, "default_cap": 500
    },
    "Shimano STEPS E8000": {
        "modes": {"Eco": 0.50, "Trail": 1.10, "Boost": 3.00},
        "efficiency": 0.75, "drag_factor": 0.9, "default_cap": 504
    },
    "Yamaha PW-X3": {
        "modes": {"+Eco": 0.50, "Eco": 1.00, "Std": 1.90, "High": 2.80, "EXPW": 3.60},
        "efficiency": 0.79, "drag_factor": 0.6, "default_cap": 720
    }
}

# --- KONSTANTEN ---
BIKE_WEIGHT, GRAVITY, AIR_DENSITY = 26.0, 9.81, 1.225
CW_AREA, CRR_FOREST = 0.72, 0.045 

st.set_page_config(page_title="Reichweitenangst", layout="wide")

# --- INITIALISIERUNG ---
if 'charges' not in st.session_state: st.session_state.charges = []
if 'modes' not in st.session_state: st.session_state.modes = []
if 'points_data' not in st.session_state: st.session_state.points_data = None

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("reichweitenangst.png"):
        st.image("reichweitenangst.png", use_container_width=True)
    st.markdown("<h2 style='text-align: center; color: #F7D106; font-size: 24px; font-weight: 900; margin: 0;'>REICHWEITENANGST</h2>", unsafe_allow_html=True)
    
    with st.expander("🔌 Antrieb", expanded=True):
        sel_motor = st.selectbox("Motor", list(MOTOR_SYSTEMS.keys()), label_visibility="collapsed")
        spec = MOTOR_SYSTEMS[sel_motor]
        if not st.session_state.modes or st.session_state.get('last_m') != sel_motor:
            st.session_state.modes = [{'id': 1, 'km': 0, 'mode': list(spec['modes'].keys())[-1]}]
            st.session_state.last_m = sel_motor

    with st.expander("👤 Setup", expanded=True):
        c1, c2 = st.columns(2)
        u_weight = c1.number_input("Fahrer Kg", 50, 150, 95)
        extra_load = c2.number_input("Last Kg", 0, 30, 5)
        rider_fit = st.select_slider("Fitness", options=["Gering", "Mittel", "Sportlich"], value="Mittel")
        temp = st.slider("Temp °C", -10, 35, 12)
        v_flat = st.slider("Ø km/h Ebene", 15, 45, 25)

    with st.expander("🔋 Akkus", expanded=True):
        m_wh = st.number_input("Akku Wh", 250, 1000, spec['default_cap'], step=10)
        has_ext = st.checkbox("Extender (+250Wh)")
        e_wh = 250 if has_ext else 0
        sp1 = st.checkbox("Ersatz 1")
        sp2 = st.checkbox("Ersatz 2")

    with st.expander("⚡ Strategie", expanded=True):
        for idx, m in enumerate(st.session_state.modes):
            mc1, mc2, mc3 = st.columns([1.2, 2.5, 0.8])
            st.session_state.modes[idx]['km'] = mc1.number_input("km", 0, 250, m['km'], key=f"mkm_{m['id']}", label_visibility="collapsed")
            st.session_state.modes[idx]['mode'] = mc2.selectbox("Mod", list(spec['modes'].keys()), 
                                                             index=list(spec['modes'].keys()).index(m['mode']) if m['mode'] in spec['modes'] else 0,
                                                             key=f"mtyp_{m['id']}", label_visibility="collapsed")
            if mc3.button("🗑️", key=f"mdel_{m['id']}"):
                st.session_state.modes.pop(idx); st.rerun()
        if st.button("➕ Wechsel", use_container_width=True):
            st.session_state.modes.append({'id': int(time.time()*1000), 'km': 20, 'mode': list(spec['modes'].keys())[0]}); st.rerun()

    with st.expander("☕ Ladestopps"):
        for idx, c in enumerate(st.session_state.charges):
            l1, l2, l3 = st.columns([1.5, 1.5, 0.8])
            st.session_state.charges[idx]['km'] = l1.number_input("km", 0, 250, c['km'], key=f"ckm_{c['id']}", label_visibility="collapsed")
            st.session_state.charges[idx]['pct'] = l2.number_input("%", 1, 100, c['pct'], key=f"cpct_{c['id']}", label_visibility="collapsed")
            if l3.button("🗑️", key=f"cdel_{c['id']}"):
                st.session_state.charges.pop(idx); st.rerun()
        if st.button("➕ Stop", use_container_width=True):
            st.session_state.charges.append({'id': int(time.time()*1000), 'km': 30, 'pct': 80}); st.rerun()

# --- RECHNERKERN ---
def run_calc(points, weight, fitness, temp, charges, modes, motor_name):
    df = pd.DataFrame(points)
    m_spec = MOTOR_SYSTEMS[motor_name]
    base_w = {"Gering": 85, "Mittel": 125, "Sportlich": 170}[fitness]
    
    df['ele_diff'], df['dist_diff'] = df['ele'].diff().fillna(0), df['dist_diff'].fillna(0)
    df['v_ms'] = np.where(df['ele_diff'] > 0, 12/3.6, v_flat/3.6)
    df['dur'] = np.where(df['v_ms'] > 0, df['dist_diff'] / df['v_ms'], 0.1)
    
    battery_stack = [{'cap': m_wh + e_wh, 'label': 'System'}]
    if sp1: battery_stack.append({'cap': m_wh + e_wh, 'label': 'Ersatz 1'})
    if sp2: battery_stack.append({'cap': m_wh + e_wh, 'label': 'Ersatz 2'})
    
    curr_idx, cons_in_curr, last_p = 0, 0, 100.0
    pcts, events, labels, markers = [], [], [], []
    active_c = sorted([dict(c) for c in charges], key=lambda x: x['km'])
    sorted_modes = sorted(modes, key=lambda x: x['km'], reverse=True)
    tf = 1.0 + (max(0, 20 - temp) * 0.008)

    for i in range(len(df)):
        km = df['cum_dist'].iloc[i]
        is_charge = False
        if active_c and km >= active_c[0]['km']:
            c = active_c.pop(0)
            target = battery_stack[curr_idx]['cap'] * (1 - c['pct']/100)
            if cons_in_curr > target: cons_in_curr = target
            is_charge = True

        p_req = ((weight * GRAVITY * df['ele_diff'].iloc[i].clip(min=0)) / df['dur'].iloc[i]) + \
                (weight * GRAVITY * CRR_FOREST * df['v_ms'].iloc[i]) + (0.5 * AIR_DENSITY * df['v_ms'].iloc[i]**3 * CW_AREA)
        
        m_curr = next((m['mode'] for m in sorted_modes if km >= m['km']), list(m_spec['modes'].keys())[0])
        supp = m_spec['modes'][m_curr]
        
        if df['ele_diff'].iloc[i] <= 0:
            e_seg = m_spec['drag_factor'] * (df['dist_diff'].iloc[i] / 1000)
        else:
            p_mot = p_req - min(p_req / (1 + supp), base_w * 1.5)
            e_seg = ((max(0, p_mot) * df['dur'].iloc[i] / 3600) / m_spec['efficiency']) * tf
            
        cons_in_curr += e_seg
        is_swap = False
        if cons_in_curr >= battery_stack[curr_idx]['cap'] and curr_idx < len(battery_stack) - 1:
            curr_idx += 1; cons_in_curr, is_swap, last_p = 0, True, 100.0
            
        p = max(0, ((battery_stack[curr_idx]['cap'] - cons_in_curr) / battery_stack[curr_idx]['cap']) * 100)
        pcts.append(p); labels.append(battery_stack[curr_idx]['label'])
        events.append('swap' if is_swap else ('charge' if is_charge else None))
        markers.append(next((t for t in [90, 80, 70, 60, 50, 40, 30, 20, 10, 0] if last_p > t >= p), None))
        last_p = p

    df['battery_pct'], df['event'], df['batt_name'], df['marker'] = pcts, events, labels, markers
    return df

# --- UI ---
file = st.file_uploader("GPX laden", type=["gpx"], label_visibility="collapsed")
if file:
    gpx = gpxpy.parse(file)
    pts, d_acc = [], 0
    for track in gpx.tracks:
        for seg in track.segments:
            for i, p in enumerate(seg.points):
                d = p.distance_3d(seg.points[i-1]) if i > 0 else 0
                d_acc += d
                pts.append({'cum_dist': d_acc/1000, 'dist_diff': d, 'ele': p.elevation})
    st.session_state.points_data = pts

if st.session_state.points_data:
    df = run_calc(st.session_state.points_data, u_weight+BIKE_WEIGHT+extra_load, rider_fit, temp, st.session_state.charges, st.session_state.modes, sel_motor)
    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("km", f"{df['cum_dist'].iloc[-1]:.1f}")
    c2.metric("hm ↑", f"{df['ele'].diff().clip(lower=0).sum():.0f}")
    c3.metric("Akku %", f"{df['battery_pct'].iloc[-1]:.1f}")
    c4.metric("Aktiv", df['batt_name'].iloc[-1])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['cum_dist'], y=df['ele'], fill='tozeroy', line=dict(width=0), fillcolor='rgba(100,100,100,0.1)', hoverinfo='skip'))
    df['color'] = np.select([df['battery_pct']>20, df['battery_pct']>10, df['battery_pct']>0], ['#00CC96', '#FFD700', '#FF851B'], default='#85144b')
    df['z_id'] = (df['color'] != df['color'].shift(1)).cumsum()
    for zid in df['z_id'].unique():
        z_df = df[df['z_id'] == zid]
        if zid > 1: z_df = pd.concat([df[df['z_id'] == zid-1].iloc[[-1]], z_df])
        fig.add_trace(go.Scatter(x=z_df['cum_dist'], y=z_df['ele'], mode='lines', line=dict(color=z_df['color'].iloc[-1], width=5), showlegend=False))
    
    m_pts = df[df['marker'].notnull()]
    if not m_pts.empty:
        fig.add_trace(go.Scatter(x=m_pts['cum_dist'], y=m_pts['ele'], mode='markers+text', text=[f"{int(m)}%" for m in m_pts['marker']], textfont=dict(size=9), textposition="top center", marker=dict(color='white', size=4)))
    
    c_pts = df[df['event'] == 'charge']
    if not c_pts.empty:
        fig.add_trace(go.Scatter(x=c_pts['cum_dist'], y=c_pts['ele'], mode='markers', marker=dict(color='#F7D106', size=20, symbol='star')))
    
    s_pts = df[df['event'] == 'swap']
    if not s_pts.empty:
        fig.add_trace(go.Scatter(x=s_pts['cum_dist'], y=s_pts['ele'], mode='markers', marker=dict(color='white', size=20, symbol='star')))
    
    fig.update_layout(xaxis_title="km", yaxis_title="m", template="plotly_dark", height=500, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)