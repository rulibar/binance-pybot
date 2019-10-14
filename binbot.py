"""
Binance Trading Bot
"""

from binance.client import Client
from datetime import datetime
import time

api_key = ""
api_secret = ""
client = Client(api_key, api_secret)

asset = "BTC"; base = "USDT"
pair = asset + base

interval_mins = 30
interval_str = str(interval_mins) + "m"

ticks = 0; days = 0

class Instance:
    def __init__(self, asset, base, interval_mins):
        self.exchange = "binance"
        self.asset = str(asset); self.base = str(base)
        self.pair = self.asset + self.base
        self.interval = int(interval_mins)
        self.ticks = 0; self.days = 0
        print("New trader instance started on {} {}m.".format(self.pair, self.interval))

        print("Getting historical candles...")
        self.candles_raw = self._candles_raw_init()
        self.candles = self._candles_init(self.candles_raw)
        self.candles_raw = self.shrink_list(self.candles_raw, 2*self.interval)
        self.candles_raw_unused = self._get_raw_unused()
        print("Historical candles loaded.")

        self.positions = self.get_positions()

    def _candles_raw_init(self) -> list:
        """
        Get enough 1m data to compile 600 historical candles
        Remove interval_mins - 2 1m data so that the next candle will come in 1-2 mins
        """
        data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(60*self.interval))
        #data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(600*self.interval))
        for i in range(self.interval - 1): data.pop()
        for i in range(len(data)): data[i] = self.get_candle(data[i])
        return data

    def _candles_init(self, candles_raw) -> list:
        # Compile the 1m candles_raw into 30m candles
        candles = list()
        candle_new = dict()
        for i in range(len(candles_raw)):
            order = (i + 1) % self.interval
            # [1, 2, ..., interval - 1, 0, 1, 2, ...]
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

    def _get_raw_unused(self) -> int:
        # Update candles_raw with recent 1m candles
        # Return how many 1m candles were imported
        raw_unused = -1
        str_out = str()
        data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(2*self.interval))
        data.pop()
        for i in range(len(data)):
            candle_raw = self.get_candle(data[i])
            if raw_unused > -1:
                raw_unused += 1
            if candle_raw["ts_end"] == self.candles[-1]["ts_end"]:
                raw_unused += 1
                continue

            if raw_unused > 0:
                self.candles_raw.append(candle_raw)
                str_out += "~ {}\n".format(candle_raw)

        print("{} current 1m candles.".format(raw_unused))
        print(str_out[:-2])
        return raw_unused

    def get_historical_candles_method(self, symbol, interval, start_str) -> list:
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

    def shrink_list(self, list_in, size) -> list:
        if len(list_in) > size:
            return list_in[-size:]
        return list_in

    def get_candle(self, data) -> dict:
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

    def init(self):
        print("~~ Init ~~")

    def tick(self):
        print("~~ Tick ~~")
        self.ticks += 1
        self.days = (self.ticks - 1) * self.interval / (60 * 24)
        print(self.ticks)
        print(self.days)
        print(self.exchange)
        print(self.pair)
        print(self.interval)
        print(self.candles[-1])
        print(self.positions)

    def get_positions(self) -> dict:
        positions = {self.asset: 0, self.base: 0}

        data = client.get_account()
        data = data["balances"]
        for i in range(len(data)):
            asset = data[i]["asset"]
            if asset not in {self.asset, self.base}: continue
            free = float(data[i]["free"])
            locked = float(data[i]["locked"])
            total = free + locked
            positions[asset] = total

        try:
            asset_diff = positions[self.asset] - self.positions[self.asset]
            base_diff = positions[self.base] - self.positions[self.base]
            print(asset_diff, base_diff)
            print(asset_diff == 0)
        except: return positions

        if asset_diff != 0 and base_diff != 0:
            avg_price = abs(asset_diff/base_diff)
            print("Avg price:", avg_price)
            print(self.candles[-1]["low"], self.candles[-1]["high"])
        elif asset_diff != 0:
            print("Change in assets detected.", asset_diff)
        elif base_diff != 0:
            print("Change in base detected.", base_diff)

        return positions

    def ping(self):
        data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(2))
        data_top = self.get_candle(data[0])
        # New raw candle?
        if data_top["ts_end"] != self.candles_raw[-1]["ts_end"]:
            self.candles_raw_unused += 1
            self.candles_raw.append(data_top)
            self.candles_raw = self.candles_raw[-2*self.interval:]

        # New candle, new tick?
        if self.candles_raw_unused == self.interval:
            candle_new = dict()
            for i in range(self.interval):
                candle_raw = self.candles_raw[-1 - i]

                if i == 0:
                    candle_new = candle_raw
                    continue

                if candle_raw["high"] > candle_new["high"]:
                    candle_new["high"] = candle_raw["high"]
                if candle_raw["low"] < candle_new["low"]:
                    candle_new["low"] = candle_raw["low"]
                candle_new["volume"] += candle_raw["volume"]

                if i == self.interval - 1:
                    candle_new["open"] = candle_raw["open"]
                    candle_new["ts_start"] = candle_raw["ts_start"]
                    self.candles.append(candle_new)
                    self.candles_raw_unused = 0
                    self.candles = self.shrink_list(self.candles, 5000)

            self.positions = self.get_positions()
            self.tick()

ins = Instance(asset, base, interval_mins)

ins.init()
while True:
    ins.ping()
    time.sleep(2)
