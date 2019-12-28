"""
Binance Trading Bot
"""

from binance.client import Client
from datetime import datetime
import time
import numpy
import talib

api_key = ""
api_secret = ""
client = Client(api_key, api_secret)

asset = "BTC"; base = "USDT"
interval_mins = 30 # [3, 240]

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

        self.deposits = dict()
        self.withdrawals = dict()
        self.deposits_pending = set()
        self.withdrawals_pending = set()
        self.earliest_pending = 0

        self.positions = self.get_positions()
        self.params = self.get_params()

    def _candles_raw_init(self) -> list:
        """ Get enough 1m data to compile 600 historical candles """
        data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(600*self.interval))
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
        print(str_out[:-1])
        return raw_unused

    def get_historical_candles_method(self, symbol, interval, start_str) -> list:
        # Get historical candles without connection problems breaking the program
        while True:
            try:
                data = client.get_historical_klines(symbol, interval, start_str)
                break
            except Exception as e:
                print("Error:", e)
                print("Sleeping for 2 seconds and then retrying.")
                time.sleep(2)
        return data

    def shrink_list(self, list_in, size) -> list:
        if len(list_in) > size: return list_in[-size:]
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

    def init_storage(self):
        print("~~ Init Storage ~~")

        price = self.candles[-1]['close']
        self.signal = {
            "rinTarget": 0,
            "rinTargetLast": 0,
            "position": "none",
            "status": 0,
            "apc": price,
            "target": price,
            "stop": price
        }

    def init(self):
        print("~~ Init ~~")

    def tick(self):
        s = self.signal

        print("Most recent candle:", self.candles[-1])
        print("Positions:", self.positions)

        close_data = numpy.array([c['close'] for c in self.candles])
        mas = round(talib.SMA(close_data, timeperiod = 20)[-1], 8)
        mal = round(talib.SMA(close_data, timeperiod = 100)[-1], 8)

        print("20 SMA:", mas)
        print("100 SMA:", mal)

        if s['position'] == "long":
            s['rinTarget'] = 1
            if mas < mal: s['rinTarget'] = 0
        else:
            s['rinTarget'] = 0
            if mas > mal: s['rinTarget'] = 1

        print("rinTarget:", s['rinTarget'])

    def bso(self):
        s = self.signal
        p = self.positions

        print("~~ bso ~~")

        rbuy = s['rinTarget'] - s['rinTargetLast']
        order_size = 0
        print("rbuy", rbuy, "p[self.asset]", p[self.asset])
        print("product", rbuy * p[self.asset])

    def get_dwts(self, diffasset, diffbase):
        # get end of previous candle, initialize vars
        ts_last = self.candles[-2]['ts_end']
        ts = self.earliest_pending
        diffasset_expt = 0.0
        diffbase_expt = 0.0

        if self.ticks == 1: # first tick
            # get all pending dws from previous week
            deposits = client.get_deposit_history(startTime = ts - 1000*60*60*24*7)['depositList']
            withdrawals = client.get_withdraw_history(startTime = ts - 1000*60*60*24*7)['withdrawList']
            # filter for asset, remove completed orders
            deposits = [d for d in deposits if d['asset'] in {asset, base} and d['status'] < 1]
            withdrawals = [w for w in withdrawals if w['asset'] in {asset, base} and w['status'] < 0]

            # Initialize deposits, deposits_pending, withdrawals, withdrawals_pending, earliest_pending
            for deposit in deposits:
                id = deposit['txId']
                self.deposits[id] = deposit
                self.deposits_pending.add(id)
                if deposit['insertTime'] < self.earliest_pending:
                    self.earliest_pending = deposit['insertTime']
            for withdrawal in withdrawals:
                id = withdrawal['id']
                self.withdrawals[id] = withdrawal
                self.withdrawals_pending.add(id)
                if withdrawal['applyTime'] < self.earliest_pending:
                    self.earliest_pending = withdrawal['applyTime']

        else: # not first tick
            # get all dws starting from 1 s before the earliest pending dw
            deposits = client.get_deposit_history(startTime = ts - 1000)['depositList']
            withdrawals = client.get_withdraw_history(startTime = ts - 1000)['withdrawList']
            # filter for asset
            deposits = [d for d in deposits if d['asset'] in {asset, base}]
            withdrawals = [w for w in withdrawals if w['asset'] in {asset, base}]

            # check if pending dws have been completed then process them
            for deposit in deposits:
                id = deposit['txId']
                if id in self.deposits_pending:
                    if deposit['status'] > 0:
                        print("Deposit processed")
                        amt = deposit['amount']
                        if deposit['asset'] == base: diffbase_expt += amt
                        else: diffasset_expt += amt
                        self.deposits[id] = deposit
                        self.deposits_pending.remove(id)
            for withdrawal in withdrawals:
                id = withdrawal['id']
                if id in self.withdrawals_pending:
                    if withdrawal['status'] > 3:
                        print("Withdrawal processed")
                        amt = withdrawal['amount'] + withdrawal['transactionFee']
                        if withdrawal['asset'] == base: diffbase_expt -= amt
                        else: diffasset_expt -= amt
                        self.withdrawals[id] = withdrawal
                        self.withdrawals_pending.remove(id)

            # check if any dws have been added in the last candle
            deposits = [d for d in deposits if d['insertTime'] > ts_last]
            withdrawals = [w for w in withdrawals if w['applyTime'] > ts_last]

            # add new dws to pending if pending or process them
            for deposit in deposits:
                id = deposit['txId']
                self.deposits[id] = deposit
                if deposit['status'] < 1: self.deposits_pending.add(id)
                else:
                    print("Deposit processed")
                    amt = deposit['amount']
                    if deposit['asset'] == base: diffbase_expt += amt
                    else: diffasset_expt += amt
            for withdrawal in withdrawals:
                id = withdrawal['id']
                self.withdrawals[id] = withdrawal
                if withdrawal['status'] < 0: self.withdrawals_pending.add(id)
                else:
                    print("Withdrawal processed")
                    amt = withdrawal['amount'] + withdrawal['transactionFee']
                    if withdrawal['asset'] == base: diffbase_expt -= amt
                    else: diffasset_expt -= amt

        print("self.deposits:")
        for id in self.deposits: print("    ~", id + ":", self.deposits[id])
        print("self.deposits_pending: ", self.deposits_pending)
        print("self.withdrawals:")
        for id in self.withdrawals: print("    ~", id + ":", self.withdrawals[id])
        print("self.withdrawals_pending: ", self.withdrawals_pending)
        print("self.earliest_pending: ", self.earliest_pending)

        # Get trades
        trades = reversed(client.get_my_trades(symbol = self.pair, limit = 20))
        trades = [t for t in trades if t['time'] > ts_last]

        # process trades
        if len(trades) > 0:
            print("{} new trade(s) found.".format(len(trades)))
            for trade in trades:
                print("~", trade)
                qty = float(trade['qty'])
                price = float(trade['price'])
                if not trade['isBuyer']: qty *= -1
                diffasset_expt += qty
                diffbase_expt -= qty * price

        # get unknown changes
        diffasset_expt = round(diffasset_expt, 8)
        diffbase_expt = round(diffbase_expt, 8)
        diffasset_unkn = diffasset - diffasset_expt
        diffbase_unkn = diffbase - diffbase_expt

        # process unknown changes
        if diffasset_unkn > 0: print(diffasset_unkn, self.asset, "has become available.")
        elif diffasset_unkn < 0: print(-diffasset_unkn, self.asset, "has become unavailable.")
        if diffbase_unkn > 0: print(diffbase_unkn, self.base, "has become available.")
        elif diffbase_unkn < 0: print(-diffbase_unkn, self.base, "has become unavailable.")

        # log outputs
        print("diffasset", diffasset)
        print("diffasset_expt", diffasset_expt)
        print("diffasset_unkn", diffasset_unkn)
        print("diffbase", diffbase)
        print("diffbase_expt", diffbase_expt)
        print("diffbase_unkn", diffbase_unkn)

        return

    def get_positions(self) -> dict:
        """ Get balances and check dwts """
        # get balances
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

        # return positions if first tick
        try:
            diff_asset = round(positions[self.asset] - self.positions[self.asset], 8)
            diff_base = round(positions[self.base] - self.positions[self.base], 8)
        except:
            ts = round(1000*time.time())
            self.earliest_pending = ts
            return positions

        # check for dwts before returning positions
        self.get_dwts(diff_asset, diff_base)
        return positions

    def get_params(self):
        """
        Compare recently imported params with previous params
        Report any changes
        /- If keys were added or removed
        /- If values were changed
        /Update self.params

        /Also handle case of initialization in __init__
        """
        params = dict()
        with open("config.txt") as cfg:
            par = [l.split()[0] for l in cfg.read().split("\n")[2:-1]]
            for p in par:
                p = p.split("=")
                if len(p) != 2: continue
                params[str(p[0])] = str(p[1])
        try:
            keys_old = {key for key in self.params}
            keys_new = {key for key in params}
        except:
            return params

        keys_added = {key for key in keys_new if key not in keys_old}
        keys_removed = {key for key in keys_old if key not in keys_new}

        if len(keys_added) > 0:
            print(len(keys_added), "parameter(s) added.")
            for key in keys_added: print("~", key, params[key])
        if len(keys_removed) > 0:
            print(len(keys_removed), "parameter(s) removed.")
            for key in keys_removed: print("~", key)

        keys_remaining = {key for key in keys_old if key in keys_new}
        keys_changed = set()

        for key in keys_remaining:
            if params[key] != self.params[key]: keys_changed.add(key)
        if len(keys_changed) > 0:
            print(len(keys_changed), "parameter(s) changed.")
            for key in keys_changed: print("~", key, self.params[key], params[key])

        return params

    def ping(self):
        """ Check for and handle a new candle """
        # New raw candle?
        data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(2))
        data_top = self.get_candle(data[0])
        if data_top["ts_end"] != self.candles_raw[-1]["ts_end"]:
            self.candles_raw_unused += 1
            self.candles_raw.append(data_top)
            self.candles_raw = self.candles_raw[-2*self.interval:]

        # New candle?
        if self.candles_raw_unused == self.interval:
            print(100*"=")
            self.params = self.get_params()
            self.ticks += 1
            self.days = (self.ticks - 1) * self.interval / (60 * 24)

            # get the new candle
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

            # get portfolio
            self.positions = self.get_positions()

            # tick
            if self.ticks == 1:
                self.init_storage()
                #self.get_seeds()
                #self.updateF()
            self.tick()
            self.bso()

ins = Instance(asset, base, interval_mins)
ins.init()

while True:
    ins.ping()
    time.sleep(2)
