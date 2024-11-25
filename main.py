import streamlit as st
import threading
import json
import time
from websocket import WebSocketApp
import logging
import pandas as pd
import plotly.graph_objs as go
from collections import deque

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

# Initialize logger
def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    return logging.getLogger()

logger = setup_logger()

price_data = pd.DataFrame(columns=["Timestamp", "Open", "High", "Low", "Close"])
ws = None
latest_price = 0.0
buffer = deque(maxlen=5)

# Conversion functions
def convert_to_coin(amount, price):
    return amount / price

def convert_to_fiat(amount, price):
    return amount * price

# WebSocket event handlers
def on_message(ws, message):
    global price_data, latest_price, buffer
    data = json.loads(message)
    if "k" in data:  # Check if the data contains candlestick info
        kline = data["k"]
        price = float(kline["c"])  # Closing price
        latest_price = price

        # Add to buffer and aggregate
        buffer.append(price)
        candlestick = aggregate_5s_candlestick()

        if candlestick:
            timestamp = pd.to_datetime(kline["t"], unit="ms")  # Use the 1-second timestamp
            new_data = pd.DataFrame([[timestamp, candlestick["open"], candlestick["high"], 
                                      candlestick["low"], candlestick["close"]]],
                                    columns=["Timestamp", "Open", "High", "Low", "Close"])
            price_data = pd.concat([price_data, new_data]).iloc[-100:]  # Keep last 100 candlesticks

def on_error(ws, error):
    logger.error(f"Error: {error}")

def on_close(ws, close_status_code, close_msg):
    logger.info("Connection closed")

def on_open(ws):
    # Subscribe to the selected coin's data
    params = {
        "method": "SUBSCRIBE",
        "params": [f"{selected_symbol}@kline_1s"],
        "id": 1
    }
    ws.send(json.dumps(params))
    logger.info(f"Subscribed to {selected_symbol} with 1-second updates")

# Aggregate 5-second candlesticks
def aggregate_5s_candlestick():
    if len(buffer) < 5:
        return None  # Wait until we have enough data for 5 seconds
    
    open_price = buffer[0]
    high_price = max(buffer)
    low_price = min(buffer)
    close_price = buffer[-1]
    return {"open": open_price, "high": high_price, "low": low_price, "close": close_price}

# WebSocket thread function
def run_websocket():
    global ws
    ws = WebSocketApp(BINANCE_WS_URL,
                      on_message=on_message,
                      on_error=on_error,
                      on_close=on_close)
    ws.on_open = on_open
    ws.run_forever()

# Streamlit app
st.title("Binance Live Crypto Tracker")

# Use session state to toggle tracking
if "tracking" not in st.session_state:
    st.session_state.tracking = False

# User inputs
if not st.session_state.tracking:
    selected_symbol = st.text_input("Enter the coin pair symbol (e.g., btcusdt, ethusdt):", "btcusdt").strip().lower()
    conversion_type = st.selectbox("Select the type of conversion:", ["Fiat to Cryptocurrency", "Cryptocurrency to Fiat"])
    amount = st.number_input("Enter the amount:", min_value=0.0, step=0.01)


if not st.session_state.tracking:
    if st.button("Start Tracking"):
        st.session_state.tracking = True
        threading.Thread(target=run_websocket, daemon=True).start()
else:
    if st.button("Stop Tracking"):
        st.session_state.tracking = False
        if ws:
            ws.close()
            ws = None

# Containers for live updates
if st.session_state.tracking:
    price_placeholder = st.empty()
    graph_placeholder = st.empty()
    conversion_placeholder = st.empty()

    while st.session_state.tracking:
        if not price_data.empty:
            # Display latest price
            price_placeholder.subheader(f"Latest Price: {latest_price:.2f} USDT")

            # Update live graph with 5-second candlesticks
            fig = go.Figure(data=go.Candlestick(
                x=price_data["Timestamp"],
                open=price_data["Open"],
                high=price_data["High"],
                low=price_data["Low"],
                close=price_data["Close"],
                name="5s Candlesticks"
            ))
            fig.update_layout(
                title="5-Second Candlestick Data",
                xaxis_title="Time",
                yaxis_title="Price (USDT)",
                xaxis=dict(type="date"),
            )
            # Add a unique key to avoid duplication error
            graph_placeholder.plotly_chart(fig, use_container_width=True, key=f"graph_{time.time()}")

            # Perform live conversion and update the placeholder
            if conversion_type == "Fiat to Cryptocurrency":
                converted_amount = convert_to_coin(amount, latest_price)
                conversion_placeholder.info(
                    f"${amount} is equivalent to {converted_amount:.6f} {selected_symbol.split('usdt')[0].upper()}"
                )
            elif conversion_type == "Cryptocurrency to Fiat":
                converted_amount = convert_to_fiat(amount, latest_price)
                conversion_placeholder.info(
                    f"{amount} {selected_symbol.split('usdt')[0].upper()} is equivalent to ${converted_amount:.2f}"
                )

        time.sleep(1)
