
import time
import statistics
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import serial
import streamlit as st

# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="ChemPulse | Smart Liquid Monitor",
    page_icon="💧",
    layout="wide"
)

BAUD_RATE = 9600
DEFAULT_PORT = "COM3"
NOMINAL_USABLE_CAPACITY_ML = 500

HISTORY_SECONDS = 5
GRAPH_HISTORY_MINUTES = 60

# =========================================================
# PHRASE DATABASE
# =========================================================

POSITIVE_PHRASES = [
    "Looking good! Keep that liquid flowing!",
    "A little progress goes a long way!",
    "Your container is having a great day!",
    "Nice! Every drop counts!",
    "Stay hydrated, stay motivated!",
    "The liquid level is looking cheerful!",
    "One drop at a time, you're doing great!",
    "Smooth filling! Keep it up!",
    "Your container is making progress!",
    "That's the spirit! Keep those drops coming!"
]

HALF_FULL_PHRASES = [
    "Halfway there! You're doing great!",
    "Look at that! We're right in the middle!",
    "50% full and 100% awesome!",
    "Half full, plenty of possibilities!",
    "We're halfway to the top!",
    "The container is feeling balanced!",
    "A perfect halfway milestone!",
    "Half the space filled, half the fun ahead!",
    "Not empty, not full — just right!",
    "Great progress! We're at the halfway mark!"
]

ALMOST_FULL_PHRASES = [
    "Getting close! Keep an eye on the level.",
    "Almost there! Slow down the filling.",
    "The container is nearing its limit.",
    "Careful now! We're approaching the top.",
    "Just a little room left. Stay alert!",
    "The level is rising. Prepare to stop soon.",
    "We're getting close to the safe limit.",
    "Easy does it! Monitor the remaining space.",
    "Nearly full! Avoid overfilling.",
    "Time to pay attention. The level is climbing!"
]

WARNING_PHRASES = [
    "WARNING! Stop filling immediately!",
    "CRITICAL LEVEL! Prevent overflow!",
    "DANGER! The container is nearly full!",
    "STOP! Maximum safe level approaching!",
    "URGENT! Do not add more liquid!",
    "OVERFILL RISK! Stop the filling process!",
    "ALERT! The container has reached a critical level!",
    "CAUTION! Additional liquid may cause overflow!",
    "HIGH LEVEL WARNING! Stop adding liquid now!",
    "SAFETY ALERT! Check the container immediately!"
]

# =========================================================
# CUSTOM STYLE
# =========================================================

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

div[data-testid="stMetric"] {
    background: rgba(120, 150, 160, 0.10);
    border: 1px solid rgba(120, 150, 160, 0.25);
    padding: 15px;
    border-radius: 12px;
}

.status-message {
    padding: 22px;
    border-radius: 14px;
    text-align: center;
    font-size: 23px;
    font-weight: 750;
    margin: 12px 0;
    border: 2px solid currentColor;
}

.status-phrase {
    text-align: center;
    font-size: 19px;
    font-weight: 600;
    min-height: 35px;
    margin-bottom: 8px;
}

.status-subtitle {
    text-align: center;
    font-size: 13px;
    opacity: 0.75;
}

.section-note {
    padding: 12px;
    border-radius: 10px;
    background: rgba(120, 150, 160, 0.10);
    margin-bottom: 12px;
}

/* Give graph sections more breathing room */
div[data-testid="stPlotlyChart"] {
    margin-bottom: 18px;
}
</style>
""", unsafe_allow_html=True)

# =========================================================
# SESSION STATE
# =========================================================

defaults = {
    "empty_distance": None,
    "latest_distance": None,
    "latest_temperature": None,
    "latest_humidity": None,
    "last_valid_reading": None,
    "monitoring": False,
    "calibration_time": None,
    "reading_history": [],
    "show_history": False,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# =========================================================
# SERIAL CONNECTION
# =========================================================

@st.cache_resource
def open_serial_connection(port):
    connection = serial.Serial(
        port=port,
        baudrate=BAUD_RATE,
        timeout=0.15
    )

    time.sleep(2)
    connection.reset_input_buffer()
    connection.reset_output_buffer()
    connection.write(b"LOCK\n")

    return connection


def send_command(connection, command):
    try:
        connection.write((command + "\n").encode("utf-8"))
    except Exception:
        pass


def parse_sensor_line(line):
    try:
        parts = line.strip().split(",")

        if len(parts) != 4 or parts[0] != "DATA":
            return None

        distance = float(parts[1])
        temperature = float(parts[2])
        humidity = float(parts[3])

        if distance <= 0 or distance > 400:
            return None

        if temperature < -50 or temperature > 100:
            temperature = None

        if humidity < 0 or humidity > 100:
            humidity = None

        return {
            "distance": distance,
            "temperature": temperature,
            "humidity": humidity
        }

    except (ValueError, TypeError):
        return None


def read_available_data(connection, max_lines=30):
    latest = None

    for _ in range(max_lines):
        try:
            if connection.in_waiting <= 0:
                break

            line = connection.readline().decode(
                "utf-8", errors="ignore"
            ).strip()

            reading = parse_sensor_line(line)

            if reading:
                latest = reading

        except Exception:
            break

    return latest

# =========================================================
# AUTOMATIC CALIBRATION
# =========================================================

def calibrate_empty_container(connection):
    send_command(connection, "LOCK")

    try:
        connection.reset_input_buffer()
    except Exception:
        pass

    readings = []
    deadline = time.time() + 12

    with st.spinner(
        "Measuring the empty container. Please keep it empty..."
    ):
        while time.time() < deadline and len(readings) < 12:
            try:
                line = connection.readline().decode(
                    "utf-8", errors="ignore"
                ).strip()

                reading = parse_sensor_line(line)

                if reading:
                    readings.append(reading["distance"])

            except Exception:
                pass

    if len(readings) < 8:
        return None, "Not enough valid sensor readings. Check the sensor."

    reference = statistics.median(readings)
    spread = max(readings) - min(readings)

    if spread > 4:
        return None, (
            "Unstable readings detected. Keep the container still "
            "and calibrate again."
        )

    return reference, None

# =========================================================
# STATUS CLASSIFICATION
# =========================================================

def get_water_status(percentage):

    if percentage <= 0:
        return {
            "title": "NO LIQUID DETECTED",
            "phrase": "The container is empty. Ready for filling!",
            "color": "#808080",
            "background": "rgba(128,128,128,0.10)",
            "category": "empty"
        }

    elif percentage < 50:
        phrase = POSITIVE_PHRASES[
            int(time.time() // 5) % len(POSITIVE_PHRASES)
        ]

        return {
            "title": "LOOKING GOOD!",
            "phrase": phrase,
            "color": "#16A34A",
            "background": "rgba(22,163,74,0.10)",
            "category": "positive"
        }

    elif percentage < 60:
        phrase = HALF_FULL_PHRASES[
            int(time.time() // 5) % len(HALF_FULL_PHRASES)
        ]

        return {
            "title": "CONTAINER IS HALF FULL!",
            "phrase": phrase,
            "color": "#16A34A",
            "background": "rgba(22,163,74,0.10)",
            "category": "half"
        }

    elif percentage <= 75:
        phrase = ALMOST_FULL_PHRASES[
            int(time.time() // 5) % len(ALMOST_FULL_PHRASES)
        ]

        return {
            "title": "CONTAINER ALMOST FULL",
            "phrase": phrase,
            "color": "#D69E00",
            "background": "rgba(214,158,0,0.12)",
            "category": "almost"
        }

    else:
        phrase = WARNING_PHRASES[
            int(time.time() // 5) % len(WARNING_PHRASES)
        ]

        return {
            "title": "WARNING!",
            "phrase": phrase,
            "color": "#DC2626",
            "background": "rgba(220,38,38,0.10)",
            "category": "warning"
        }

# =========================================================
# HISTORY FUNCTIONS
# =========================================================

def save_history(percentage, temperature, humidity):

    now = time.time()

    st.session_state.reading_history.append({
        "timestamp": now,
        "time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
        "water_level": round(percentage, 1),
        "temperature": temperature,
        "humidity": humidity
    })

    # Keep up to 60 minutes of readings for graph display.
    cutoff = now - (GRAPH_HISTORY_MINUTES * 60)

    st.session_state.reading_history = [
        item
        for item in st.session_state.reading_history
        if item["timestamp"] >= cutoff
    ]


def get_recent_history(seconds=HISTORY_SECONDS):

    now = time.time()

    return [
        item
        for item in st.session_state.reading_history
        if now - item["timestamp"] <= seconds
    ]

# =========================================================
# FULL-HISTORY LINE GRAPH FUNCTION
# =========================================================

def create_sensor_graph(
    data,
    value_column,
    graph_title,
    y_axis_title,
    y_min,
    y_max,
    line_color,
    suffix=""
):

    fig = go.Figure()

    if not data.empty:

        fig.add_trace(
            go.Scatter(
                x=data["datetime"],
                y=data[value_column],
                mode="lines",
                name=graph_title,
                connectgaps=False,
                line=dict(
                    color=line_color,
                    width=3,
                    shape="linear"
                ),
                hovertemplate=(
                    "<b>%{y:.1f}" + suffix + "</b><br>"
                    "%{x|%b %d, %H:%M:%S}"
                    "<extra></extra>"
                )
            )
        )

    fig.update_layout(
        title=dict(
            text=graph_title,
            x=0.02,
            xanchor="left",
            font=dict(size=19)
        ),
        height=420,
        autosize=True,
        margin=dict(
            l=65,
            r=30,
            t=65,
            b=65
        ),
        showlegend=False,
        hovermode="x",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(120,150,160,0.05)",
        font=dict(
            family="Arial",
            size=13
        ),
        xaxis=dict(
            title="Time",
            type="date",
            autorange=True,
            tickformat="%H:%M:%S",
            showgrid=True,
            gridcolor="rgba(120,150,160,0.18)",
            zeroline=False,
            showline=True,
            linecolor="rgba(120,150,160,0.35)",
            rangeslider=dict(
                visible=True,
                thickness=0.08
            )
        ),
        yaxis=dict(
            title=y_axis_title,
            range=[y_min, y_max],
            autorange=False,
            fixedrange=False,
            showgrid=True,
            gridcolor="rgba(120,150,160,0.18)",
            zeroline=False,
            showline=True,
            linecolor="rgba(120,150,160,0.35)"
        ),
        dragmode="pan"
    )

    return fig

# =========================================================
# GRAPH DISPLAY CONFIGURATION
# =========================================================

GRAPH_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": True,
    "doubleClick": "reset",
    "modeBarButtonsToRemove": [
        "select2d",
        "lasso2d"
    ]
}

# =========================================================
# HEADER
# =========================================================

st.title("ChemPulse")
st.caption("Smart Liquid Level and Environmental Monitoring System")

# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:

    st.header("System Settings")

    port = st.text_input(
        "Arduino Serial Port",
        value=DEFAULT_PORT
    )

    if st.button("Reconnect Arduino", use_container_width=True):
        try:
            open_serial_connection.clear()
            st.rerun()
        except Exception as error:
            st.error(str(error))

    st.divider()

    st.subheader("Water-Level Safety")

    safety_clearance = st.slider(
        "Minimum distance below sensor",
        min_value=2.0,
        max_value=10.0,
        value=6.0,
        step=0.5
    )

    st.metric(
        "Safety Clearance",
        f"{safety_clearance:.1f} cm"
    )

    st.divider()

    st.metric(
        "Nominal Usable Capacity",
        f"{NOMINAL_USABLE_CAPACITY_ML} mL"
    )

    st.caption(
        "Volume is an estimate. Actual volume depends on container geometry."
    )

# =========================================================
# CONNECT TO ARDUINO
# =========================================================

try:
    connection = open_serial_connection(port)

except Exception as error:
    st.error(f"Could not connect to Arduino on {port}.")
    st.code(str(error))
    st.stop()

# =========================================================
# CALIBRATION
# =========================================================

st.subheader("Container Calibration")

if st.session_state.empty_distance is None:

    st.warning("Calibration required. Empty the container first.")

else:

    st.success(
        f"Empty reference: "
        f"{st.session_state.empty_distance:.2f} cm"
    )

if st.button(
    "Calibrate Empty Container",
    type="primary",
    use_container_width=True
):

    st.session_state.monitoring = False
    st.session_state.empty_distance = None
    st.session_state.reading_history = []

    send_command(connection, "LOCK")

    reference, error_message = calibrate_empty_container(connection)

    if error_message:
        st.error(error_message)

    else:
        st.session_state.empty_distance = reference
        st.session_state.calibration_time = datetime.now()
        st.session_state.latest_distance = None
        st.session_state.last_valid_reading = None

        st.success(
            f"Calibration successful! Reference: {reference:.2f} cm"
        )

        st.rerun()

# =========================================================
# CHECK CALIBRATION
# =========================================================

empty_distance = st.session_state.empty_distance

if empty_distance is None:
    send_command(connection, "LOCK")
    st.info("Please calibrate the empty container first.")
    st.stop()

usable_height = empty_distance - safety_clearance

if usable_height <= 0:
    send_command(connection, "LOCK")
    st.error("Invalid safety clearance. Check your settings.")
    st.stop()

# =========================================================
# MONITORING CONTROLS
# =========================================================

st.subheader("Monitoring Controls")

col1, col2 = st.columns(2)

with col1:

    if st.button(
        "Start Monitoring",
        type="primary",
        use_container_width=True
    ):
        st.session_state.monitoring = True
        st.rerun()

with col2:

    if st.button(
        "Stop Monitoring",
        use_container_width=True
    ):
        st.session_state.monitoring = False
        st.session_state.show_history = False
        send_command(connection, "LOCK")
        st.rerun()

if not st.session_state.monitoring:
    send_command(connection, "LOCK")
    st.info("Monitoring is currently stopped.")
    st.stop()

# =========================================================
# LIVE DASHBOARD
# =========================================================

@st.fragment(run_every=1)
def live_dashboard():

    # -----------------------------------------------------
    # GET LATEST SENSOR DATA
    # -----------------------------------------------------

    reading = read_available_data(connection)

    if reading:

        st.session_state.latest_distance = reading["distance"]
        st.session_state.latest_temperature = reading["temperature"]
        st.session_state.latest_humidity = reading["humidity"]
        st.session_state.last_valid_reading = time.time()

    last_reading_time = st.session_state.last_valid_reading

    if (
        last_reading_time is None
        or time.time() - last_reading_time > 4
    ):

        send_command(connection, "LOCK")

        st.error(
            "No recent sensor reading. Outputs have been locked. "
            "Check the sensor and serial connection."
        )

        return

    # -----------------------------------------------------
    # WATER LEVEL CALCULATION
    # -----------------------------------------------------

    current_distance = st.session_state.latest_distance

    raw_height = empty_distance - current_distance

    water_height = max(
        0.0,
        min(raw_height, usable_height)
    )

    percentage = (water_height / usable_height) * 100

    percentage = max(0.0, min(percentage, 100.0))

    if percentage < 0.5:
        percentage = 0.0
        water_height = 0.0

    estimated_volume = (
        NOMINAL_USABLE_CAPACITY_ML * percentage / 100
    )

    temperature = st.session_state.latest_temperature
    humidity = st.session_state.latest_humidity

    # -----------------------------------------------------
    # SEND STATUS TO ARDUINO
    # -----------------------------------------------------

    temperature_for_arduino = (
        temperature if temperature is not None else 0
    )

    send_command(
        connection,
        f"STATUS,{percentage:.1f},{temperature_for_arduino:.1f}"
    )

    # -----------------------------------------------------
    # SAVE HISTORY
    # -----------------------------------------------------

    save_history(
        percentage,
        temperature,
        humidity
    )

    # -----------------------------------------------------
    # GET STATUS
    # -----------------------------------------------------

    status = get_water_status(percentage)

    # -----------------------------------------------------
    # CREATE THREE TABS
    # -----------------------------------------------------

    tab_water, tab_environment, tab_graph = st.tabs([
        "Water Monitoring",
        "Environmental Monitoring",
        "Real-Time Graph"
    ])

    # =====================================================
    # TAB 1: WATER MONITORING
    # =====================================================

    with tab_water:

        st.subheader("Water-Level Monitoring")

        st.markdown(
            f"""
            <div class="status-message"
                 style="color:{status['color']};
                        background:{status['background']};">
                {status['title']}
            </div>

            <div class="status-phrase"
                 style="color:{status['color']};">
                {status['phrase']}
            </div>

            <div class="status-subtitle"
                 style="color:{status['color']};">
                Status messages change every 5 seconds.
            </div>
            """,
            unsafe_allow_html=True
        )

        st.divider()

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Water Level",
            f"{percentage:.1f}%"
        )

        c2.metric(
            "Estimated Volume",
            f"{estimated_volume:.0f} mL"
        )

        c3.metric(
            "Water Height",
            f"{water_height:.2f} cm"
        )

        st.progress(int(round(percentage)))

        st.caption(
            f"Sensor-to-water distance: {current_distance:.2f} cm"
        )

        st.caption(
            f"Empty reference: {empty_distance:.2f} cm | "
            f"Safe usable height: {usable_height:.2f} cm | "
            f"Safety clearance: {safety_clearance:.1f} cm"
        )

        if current_distance < safety_clearance:

            st.error(
                "SAFETY LIMIT EXCEEDED: Water is closer to the "
                "sensor than the configured safety clearance."
            )

        elif percentage == 0:

            st.info("No liquid detected in the container.")

        elif percentage >= 76:

            st.error("Stop filling immediately.")

        elif percentage >= 60:

            st.warning("The container is approaching its safe limit.")

        else:

            st.success("Water level is within the lower filling range.")

    # =====================================================
    # TAB 2: ENVIRONMENTAL MONITORING
    # =====================================================

    with tab_environment:

        st.subheader("Environmental Monitoring")

        st.caption(
            "The DHT11 measures the surrounding air temperature "
            "and relative humidity."
        )

        env1, env2 = st.columns(2)

        with env1:

            st.metric(
                "Temperature",
                f"{temperature:.1f} °C"
                if temperature is not None else "--"
            )

            st.markdown("**Temperature Guide**")

            st.markdown("""
            - **Below 18°C:** Relatively cool conditions. Some
              temperature-sensitive processes may slow down.
            - **18–30°C:** Generally moderate room conditions.
            - **Above 30°C:** Warmer surroundings. Evaporation may
              increase, and temperature-sensitive materials may be affected.
            - **35°C and above:** High-temperature alert for this project.
              Check the surrounding environment and process conditions.
            """)

        with env2:

            st.metric(
                "Relative Humidity",
                f"{humidity:.1f}%"
                if humidity is not None else "--"
            )

            st.markdown("**Humidity Guide**")

            st.markdown("""
            - **Below 30%:** Dry air. It may cause faster evaporation
              and drying of exposed materials.
            - **30–60%:** A commonly comfortable indoor humidity range.
            - **Above 60%:** Moist air. Condensation and mold growth
              may become more likely over time.
            - **Above 70%:** Very humid conditions. Monitor moisture
              buildup and ventilation.
            """)

        st.divider()

        st.subheader("Why These Readings Matter")

        st.markdown("""
        **Temperature** affects evaporation rates and can influence
        chemical and physical processes.

        **Relative humidity** describes how much water vapor is present
        in the surrounding air compared with the maximum it can hold
        at that temperature.

        Changes in temperature and humidity do not automatically mean
        a process is unsafe. Their effects depend on the material,
        equipment, and operating conditions.
        """)

        if temperature is not None and temperature >= 35:

            st.warning(
                "Temperature alert: The measured air temperature "
                "is at or above 35°C."
            )

        if humidity is not None and humidity > 70:

            st.warning(
                "High humidity: Moisture buildup may become more likely."
            )

        if humidity is not None and humidity < 30:

            st.info(
                "Low humidity: The surrounding air is relatively dry."
            )

    # =====================================================
    # TAB 3: REAL-TIME GRAPHS AND HISTORY
    # =====================================================

    with tab_graph:

        st.subheader("Real-Time Sensor Graphs")

        st.caption(
            "Each graph displays the available readings from the current "
            "monitoring session, up to the last 60 minutes. "
            "The vertical scales show the full measurement range."
        )

        graph_data = pd.DataFrame(
            st.session_state.reading_history
        )

        if not graph_data.empty:

            graph_data["datetime"] = pd.to_datetime(
                graph_data["timestamp"],
                unit="s"
            )

            # ---------------------------------------------
            # WATER LEVEL GRAPH
            # ---------------------------------------------

            st.markdown("### Water Level")

            water_graph = graph_data[
                ["datetime", "water_level"]
            ].dropna()

            if not water_graph.empty:

                st.plotly_chart(
                    create_sensor_graph(
                        water_graph,
                        "water_level",
                        "Water Level",
                        "Water Level (%)",
                        0,
                        100,
                        "#16A34A",
                        "%"
                    ),
                    use_container_width=True,
                    config=GRAPH_CONFIG,
                    key="water_level_graph"
                )

            else:

                st.info("No water-level readings available yet.")

            # ---------------------------------------------
            # TEMPERATURE GRAPH
            # ---------------------------------------------

            st.markdown("### Temperature")

            temp_graph = graph_data[
                ["datetime", "temperature"]
            ].dropna()

            if not temp_graph.empty:

                st.plotly_chart(
                    create_sensor_graph(
                        temp_graph,
                        "temperature",
                        "Temperature",
                        "Temperature (°C)",
                        0,
                        50,
                        "#F59E0B",
                        " °C"
                    ),
                    use_container_width=True,
                    config=GRAPH_CONFIG,
                    key="temperature_graph"
                )

            else:

                st.info("No valid temperature readings yet.")

            # ---------------------------------------------
            # HUMIDITY GRAPH
            # ---------------------------------------------

            st.markdown("### Relative Humidity")

            humidity_graph = graph_data[
                ["datetime", "humidity"]
            ].dropna()

            if not humidity_graph.empty:

                st.plotly_chart(
                    create_sensor_graph(
                        humidity_graph,
                        "humidity",
                        "Relative Humidity",
                        "Humidity (%)",
                        0,
                        100,
                        "#3B82F6",
                        "%"
                    ),
                    use_container_width=True,
                    config=GRAPH_CONFIG,
                    key="humidity_graph"
                )

            else:

                st.info("No valid humidity readings yet.")

        else:

            st.info("Waiting for sensor readings...")

        st.divider()

        # ---------------------------------------------
        # HISTORY BUTTON
        # ---------------------------------------------

        history_col1, history_col2 = st.columns([1, 3])

        with history_col1:

            button_label = (
                "Hide History"
                if st.session_state.show_history
                else "History"
            )

            if st.button(
                button_label,
                use_container_width=True
            ):

                st.session_state.show_history = (
                    not st.session_state.show_history
                )

        with history_col2:

            st.caption(
                "View the sensor readings recorded during the last 5 seconds."
            )

        if st.session_state.show_history:

            st.markdown("### Recent Reading History")

            recent = get_recent_history(HISTORY_SECONDS)

            if recent:

                history_table = pd.DataFrame(recent)

                history_table = history_table[
                    [
                        "time",
                        "water_level",
                        "temperature",
                        "humidity"
                    ]
                ].copy()

                history_table.columns = [
                    "Time",
                    "Water Level (%)",
                    "Temperature (°C)",
                    "Humidity (%)"
                ]

                st.dataframe(
                    history_table.iloc[::-1],
                    use_container_width=True,
                    hide_index=True
                )

                st.caption(
                    "Old readings automatically disappear from this table "
                    "after 5 seconds. Graph data is retained for up to 60 minutes."
                )

            else:

                st.info("No recent history available.")

        st.divider()

        st.caption(
            "Last sensor update: " +
            datetime.fromtimestamp(
                st.session_state.last_valid_reading
            ).strftime("%H:%M:%S")
        )


live_dashboard()
