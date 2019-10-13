"""
Binance Trading Bot
"""

from binance.client import Client
from datetime import datetime
import time

exchange = "binance"
api_key = ""
api_secret = ""

asset = "BTC"; base = "USDT"
pair = asset + base
interval_mins = 30
interval_str = str(interval_mins) + "m"

ticks = 0; days = 0

client = Client(api_key, api_secret)

def shrink(list_in, size) -> list:
    if len(list_in) > size:
        return list_in[-size:]
    return list_in

def get_candle(data) -> dict:
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

def get_historical_candles_method(symbol, interval, start_str) -> list:
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

def get_historical_candles() -> list:
    """
    Get enough 1m data to compile 600 historical candles
    Remove interval_mins - 2 1m data so that the next candle will come in 1-2 mins
    """
    data = get_historical_candles_method(pair, "1m", "{} minutes ago UTC".format(60*interval_mins))
    #data = get_historical_candles_method(pair, "1m", "{} minutes ago UTC".format(600*interval_mins))
    for i in range(interval_mins - 1): data.pop()
    for i in range(len(data)): data[i] = get_candle(data[i])
    return data

def compile_raw(candles_raw) -> list:
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

def get_current_candles() -> int:
    # Update candles_raw with recent 1m candles
    # Return how many 1m candles were imported
    unused_1m = -1
    str_out = str()
    data = get_historical_candles_method("BTCUSDT", "1m", "{} minutes ago UTC".format(2*interval_mins))
    data.pop()
    for i in range(len(data)):
        candle_raw = get_candle(data[i])
        if unused_1m > -1:
            unused_1m += 1
        if candle_raw["ts_end"] == candles[len(candles) - 1]["ts_end"]:
            unused_1m += 1
            continue

        if unused_1m > 0:
            candles_raw.append(candle_raw)
            str_out += "~ {}\n".format(candle_raw)

    print("{} current 1m candles.".format(unused_1m))
    print(str_out[:-2])
    return unused_1m

# Get historical candles
print("Getting historical candles.\n.\t.\t.")
candles_raw = get_historical_candles()
candles = compile_raw(candles_raw)
candles_raw = shrink(candles_raw, 2*interval_mins)
print("Historical candles loaded.")

# Get current candles
unused_1m = get_current_candles()

##### Algorithm section

def init():
    print("~~ Init ~~")

def tick():
    print("~~ Tick ~~")

init()

while True:
    data = get_historical_candles_method("BTCUSDT", "1m", "{} minutes ago UTC".format(2))
    data_top = get_candle(data[0])
    # New raw candle?
    if data_top["ts_end"] != candles_raw[len(candles_raw) - 1]["ts_end"]:
        unused_1m += 1
        candles_raw.append(data_top)
        candles_raw = candles_raw[len(candles_raw) - 2*interval_mins:]

    # New candle, new tick?
    if unused_1m == interval_mins:
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
                unused_1m = 0
                candles = shrink(candles, 5000)

        ticks += 1
        days = (ticks - 1) * interval_mins / (60 * 24)
        tick()

    time.sleep(2)
