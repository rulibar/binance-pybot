"""
Binance Trading Bot
"""

from binance.client import Client
from datetime import datetime
import time

pair = "BTCUSDT"
interval_mins = 30

api_key = ""
api_secret = ""

client = Client(api_key, api_secret)
interval_str = str(interval_mins) + "m"

def shrink(given_array, size):
    if len(given_array) > size:
        return given_array[-size:]
    return given_array

def get_candle(data):
    # data is a kline list from Binance
    candle = {
        "ts_start": int(data[0]),
        "open": float(data[1]),
        "high": float(data[2]),
        "low": float(data[3]),
        "close": float(data[4]),
        "volume": float(data[5]),
        "ts_end": int(data[6])
    }
    return candle

##### Preliminary section
def get_historical_candles_method(symbol, interval, start_str):
    # Get historical candles without connection problems breaking the program
    while True:
        try:
            data = client.get_historical_klines(symbol, interval, start_str)
            break
        except:
            print("Error: An unknown error occurred while getting candles.")
            print("Sleeping for 2 seconds and then retrying.")
            time.sleep(2)

    return data

def get_historical_candles():
    # Get 1m data over the past week
    # Remove recent data so that the next tick comes in 1-2 minutes
    data = get_historical_candles_method(pair, "1m", "2 days ago UTC")
    for i in range(interval_mins - 1): data.pop()
    for i in range(len(data)): data[i] = get_candle(data[i])
    return data

def compile_raw(candles_raw):
    # Compile the 1m candles_raw into 30m candles
    candle_new = dict()
    candles = list()
    for i in range(len(candles_raw)):
        order = (i + 1) % interval_mins
        # [1, 2, ..., interval_mins - 1, 0, 1, 2, ...]
        candle_raw = candles_raw[len(candles_raw) - 1 - i]
        # Going backwards through candles_raw to have control over how long
        # until next candle

        if order == 1:
            candle_new = candle_raw
            continue

        if candle_raw["high"] > candle_new["high"]:
            candle_new["high"] = candle_raw["high"]
        if candle_raw["low"] < candle_new["low"]:
            candle_new["low"] = candle_raw["low"]
        candle_new["volume"] += candle_raw["volume"]

        if order == 0:
            candle_new["open"] = candle_raw["open"]
            candle_new["ts_start"] = candle_raw["ts_start"]
            candles.append(candle_new)

    return candles[::-1]

def get_current_candles():
    # Update candles_raw with recent 1m candles
    # Return how many 1m candles were imported
    unused_1m = -1
    data = get_historical_candles_method("BTCUSDT", "1m", "{} minutes ago UTC".format(2*interval_mins))
    data.pop()
    for i in range(len(data)):
        candle_raw = get_candle(data[i])
        if unused_1m > -1:
            unused_1m += 1
        if candle_raw["ts_end"] == candles[len(candles) - 1]["ts_end"]:
            unused_1m += 1
            continue

        if unused_1m == 1:
            candles_raw.append(candle_raw)
            print("new raw candles")
            print("~ {}".format(candle_raw))
            continue
        if unused_1m > 0:
            candles_raw.append(candle_raw)
            print("~ {}".format(candle_raw))

    return unused_1m

# Get historical candles
print("Getting historical candles.\n.\t.\t.")
candles_raw = get_historical_candles()
candles = compile_raw(candles_raw)
candles_raw = shrink(candles_raw, 10*interval_mins)
print("Historical candles loaded.")

# Get current candles
unused_1m = get_current_candles()
print("{} current 1m candles.".format(unused_1m))

##### Algorithm section

def init():
    print("~~ Init ~~")

def tick():
    print("~~ Tick ~~")

init()

while True:
    data = get_historical_candles_method("BTCUSDT", "1m", "{} minutes ago UTC".format(interval_mins))
    print(get_candle(data.pop()))
    data_top = get_candle(data[len(data) - 1])
    if data_top["ts_end"] != candles_raw[len(candles_raw) - 1]["ts_end"]:
        print("new raw candle")
        print("~ {}".format(data_top))
        unused_1m += 1
        candles_raw.append(data_top)
        candles_raw = candles_raw[len(candles_raw) - 10*interval_mins:]

    if unused_1m == interval_mins:
        print("new candle")
        candle_new = dict()
        for i in range(interval_mins):
            candle_raw = candles_raw[len(candles_raw) - 1 - i]

            if i == 0:
                candle_new = candle_raw
                continue

            if candle_raw["high"] > candle_new["high"]:
                candle_new["high"] = candle_raw["high"]
            if candle_raw["low"] < candle_new["low"]:
                candle_new["low"] = candle_raw["low"]
            candle_new["volume"] += candle_raw["volume"]

            if i == interval_mins - 1:
                candle_new["open"] = candle_raw["open"]
                candle_new["ts_start"] = candle_raw["ts_start"]
                candles.append(candle_new)
                print("~ {}".format(candle_new))
                unused_1m = 0
                candles = shrink(candles, 300*interval_mins)

        tick()

    time.sleep(2)
