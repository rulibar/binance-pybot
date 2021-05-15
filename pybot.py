"""
Binance Pybot v0.2.1 (21-05-15)
https://github.com/rulibar/binance-pybot
"""

import os
import time
from calendar import timegm as timegm
import numpy
import random
import logging
import talib
from binance.client import Client

# instance vars
api_key = ""
api_secret = ""
client = Client(api_key, api_secret)

asset = "BTC"; base = "USDT"
interval_mins = 30

# strategy vars
storage = dict()

# set up logger
def set_log_file():
    # Set up the log folders
    gmt = time.gmtime()
    yy = str(gmt.tm_year)[2:]; mm = str(gmt.tm_mon); dd = str(gmt.tm_mday)
    if len(mm) == 1: mm = "0" + mm
    if len(dd) == 1: dd = "0" + dd
    path = "./logs/"
    if not os.path.isdir(path): os.mkdir(path)
    path += "{}/".format(yy + mm)
    if not os.path.isdir(path): os.mkdir(path)
    # Set the log destination and format
    fileh = logging.FileHandler("./logs/{}/{}.log".format(yy + mm, yy + mm + dd), "a")
    formatter = logging.Formatter("%(levelname)s %(asctime)s - %(message)s")
    fileh.setFormatter(formatter)
    logger.handlers = [fileh]

logging.basicConfig(level=logging.INFO)
logging.Formatter.converter = time.gmtime
logger = logging.getLogger()
set_log_file()

# set up trading bot
def fix_dec(float_in):
    float_out = "{:.8f}".format(float_in)
    while float_out[-1] == "0": float_out = float_out[:-1]
    if float_out[-1] == ".": float_out = float_out[:-1]
    return float_out

def shrink_list(list_in, size):
    if len(list_in) > size: return list_in[-size:]
    return list_in

class Portfolio:
    def __init__(self, candle, positions, funds):
        self.ts = candle['ts_end']
        self.asset = positions['asset'][1]
        self.base = positions['base'][1]
        self.price = candle['close']
        self.positionValue = self.price * self.asset
        self.size = self.base + self.positionValue
        self.funds = funds
        if funds > self.size or funds == 0: self.funds = float(self.size)
        self.sizeT = float(self.funds)
        self.rin = self.price * self.asset / self.size
        self.rinT = self.price * self.asset / self.sizeT

class Instance:
    def __init__(self, asset, base, interval_mins):
        self.next_log = 0
        self.ticks = 0; self.days = 0; self.trades = 0
        self.exchange = "binance"
        self.base = str(base)
        self.asset = str(asset)
        self.pair = self.asset + self.base
        self.interval = int(interval_mins)
        logger.info("New trader instance started on {} {} {}m.".format(self.exchange.title(), self.pair, self.interval))
        self.get_params()

        self.candles_raw = self._get_candles_raw()
        self.candles = self._get_candles()
        self.candles_raw = shrink_list(self.candles_raw, 2 * self.interval)
        self.candles_raw_unused = self._get_raw_unused()

        self.deposits_pending = set()
        self.withdrawals_pending = set()
        self.earliest_pending = 0

        self.candle_start = None
        self.positions_start = None
        self.positions_init_ts = 0
        self.positions = self.get_positions()
        self.positions_f = {'asset': list(self.positions['asset'])}
        self.positions_f['base'] = list(self.positions['base'])
        self.positions_t = {'asset': list(self.positions['asset'])}
        self.positions_t['base'] = list(self.positions['base'])
        p = Portfolio(self.candles[-1], self.positions, float(self.params['funds']))
        self.last_order = {"type": "none", "amt": 0, "pt": self.candles[-1]['close']}
        self.signal = {"rinTarget": p.rinT, "rinTargetLast": p.rinT, "position": "none", "status": 0, "apc": p.price, "target": p.price, "stop": p.price}
        self.performance = {"bh": 0, "change": 0, "W": 0, "L": 0, "wSum": 0, "lSum": 0, "w": 0, "l": 0, "be": 0, "aProfits": 0, "bProfits": 0, "cProfits": 0}
        self.init(p)

    def _get_candles_raw(self):
        # get enough 1m candles to create 600 historical candles
        data = self.get_historical_candles(self.pair, "1m", 600 * self.interval)
        data.pop()
        for i in range(len(data)): data[i] = self.get_candle(data[i])
        return data

    def _get_candles(self):
        # convert historical 1m candles into historical candles
        candles = list(); candle_new = dict()
        candles_raw_clone = list(self.candles_raw)
        for i in range(self.interval - 2): candles_raw_clone.pop()
        for i in range(len(candles_raw_clone)):
            order = i % self.interval
            candle_raw = candles_raw_clone[- 1 - i]

            if order == 0:
                candle_new = candle_raw
                continue

            if candle_raw["high"] > candle_new["high"]:
                candle_new["high"] = candle_raw["high"]
            if candle_raw["low"] < candle_new["low"]:
                candle_new["low"] = candle_raw["low"]
            candle_new["volume"] += candle_raw["volume"]

            if order == self.interval - 1:
                candle_new["open"] = candle_raw["open"]
                candle_new["ts_start"] = candle_raw["ts_start"]
                candles.append(candle_new)

        return candles[::-1]

    def _get_raw_unused(self):
        # get unused historical 1m candles
        raw_unused = -1
        str_out = str()
        data = self.candles_raw[-2 * self.interval:]
        for i in range(len(data)):
            candle_raw = data[i]
            if raw_unused > -1:
                raw_unused += 1
            if candle_raw["ts_end"] == self.candles[-1]["ts_end"]:
                raw_unused += 1
                continue

            if raw_unused > 0: str_out += "    {}\n".format(candle_raw)

        return raw_unused

    def get_historical_candles_method(self, symbol, interval, start_str):
        data, err = list(), str()
        try: data = client.get_historical_klines(symbol, interval, start_str)
        except Exception as e: err = e
        return data, err

    def get_historical_candles(self, symbol, interval, n_candles):
        tries = 0
        while True:
            data, err = self.get_historical_candles_method(symbol, interval, "{} minutes ago UTC".format(n_candles))
            tries += 1
            if len(data) == 0:
                if tries <= 3:
                    err_msg = "Error getting historical candle data. Retrying in 5 seconds..."
                    if err != "": err_msg += "\n'{}'".format(err)
                    logger.error(err_msg)
                if tries == 3: logger.error("(Future repeats of this error hidden to avoid spam.)")
                time.sleep(5)
            else: break
        if tries > 3: logger.error("Failed to get historical candle data {} times.".format(tries - 1))
        return data

    def get_candle(self, data):
        # data is a kline list from Binance
        candle = {
            "ts_start": int(data[0]),
            "open": round(float(data[1]), 8),
            "high": round(float(data[2]), 8),
            "low": round(float(data[3]), 8),
            "close": round(float(data[4]), 8),
            "volume": round(float(data[5]), 8),
            "ts_end": int(data[6])}
        return candle

    def limit_buy(self, amt, pt):
        try:
            logger.warning("Trying to buy {} {} for {} {}. (price: {})".format(fix_dec(amt), self.asset, fix_dec(round(amt * pt, self.pt_dec)), self.base, fix_dec(pt)))
            self.last_order = {"type": "buy", "amt": amt, "pt": pt}
            client.order_limit_buy(symbol = self.pair, quantity = "{:.8f}".format(amt), price = "{:.8f}".format(pt))
        except Exception as e:
            logger.error("Error buying.\n'{}'".format(e))

    def limit_sell(self, amt, pt):
        try:
            logger.warning("Trying to sell {} {} for {} {}. (price: {})".format(fix_dec(amt), self.asset, fix_dec(round(amt * pt, self.pt_dec)), self.base, fix_dec(pt)))
            self.last_order = {"type": "sell", "amt": amt, "pt": pt}
            client.order_limit_sell(symbol = self.pair, quantity = "{:.8f}".format(amt), price = "{:.8f}".format(pt))
        except Exception as e:
            logger.error("Error selling.\n'{}'".format(e))

    def bso(self, p):
        # buy/sell/other
        s = self.signal

        rbuy = s['rinTarget'] - s['rinTargetLast']
        order_size = 0
        if rbuy * p.asset >= 0:
            order_size = abs(rbuy * p.funds)
            if order_size > p.base: order_size = p.base
        if rbuy * p.asset < 0:
            rbuy_asset = rbuy / s['rinTargetLast']
            order_size = abs(rbuy_asset * p.asset * p.price)
        if order_size < self.min_order: order_size = 0

        if order_size > 0:
            if rbuy > 0: pt = (1 + 0.0015) * p.price
            else: pt = (1 - 0.0015) * p.price
            pt = round(pt, self.pt_dec)
            if rbuy > 0: amt = order_size / pt
            else: amt = order_size / p.price
            amt = round(0.995 * amt * 10**self.amt_dec - 2) / 10**self.amt_dec
            if rbuy > 0: self.limit_buy(amt, pt)
            if rbuy < 0: self.limit_sell(amt, pt)
        if rbuy == 0: order_size = 0
        if order_size == 0:
            if self.ticks == 1: logger.info("Waiting for a signal to trade...")
            self.last_order = {"type": "none", "amt": 0, "pt": p.price}

    def close_orders(self):
        # close open orders
        try:
            orders = client.get_open_orders(symbol = self.pair)
            for order in orders:
                client.cancel_order(symbol = self.pair, orderId = order['orderId'])
        except Exception as e:
            logger.error("Error closing open orders.\n'{}'".format(e))

    def update_vars(self):
        # Get preliminary vars
        self.ticks += 1
        self.days = (self.ticks - 1) * self.interval / (60 * 24)

        try: data = client.get_symbol_info(self.pair)['filters']
        except Exception as e:
            logger.error("Error getting symbol info.\n'{}'".format(e))
            return
        min_order = float(data[2]['minQty']) * self.candles[-1]['close']
        self.min_order = 3 * max(min_order, float(data[3]['minNotional']))
        amt_dec = 8
        for char in reversed(data[2]['stepSize']):
            if char == "0": amt_dec -= 1
            else: break
        self.amt_dec = amt_dec
        pt_dec = 8
        for char in reversed(data[0]['tickSize']):
            if char == "0": pt_dec -= 1
            else: break
        self.pt_dec = pt_dec

    def get_params(self):
        # import and process params from config.txt
        params = dict()
        with open("config.txt") as cfg:
            par = [l.split()[0] for l in cfg.read().split("\n")[2:-1]]
            for p in par:
                p = p.split("=")
                if len(p) != 2: continue
                params[str(p[0])] = str(p[1])

        # check values
        funds = float(params['funds'])
        if funds < 0:
            logger.warning("Warning! Maximum amount to invest should be zero or greater.")
            params['funds'] = "0"

        logs_per_day = float(params['logs_per_day'])
        if logs_per_day < 0:
            logger.warning("Warning! Logs per day should be zero or greater.")
            params['logs_per_day'] = "1"

        log_dws = str(params['log_dws'])
        if log_dws not in {"yes", "no"}:
            logger.warning("Warning! Log deposits and withdrawals set to 'yes'.")
            params['log_dws'] = "yes"

        # check for additions and removals
        if self.ticks == 0: self.params = dict()

        keys_old = {key for key in self.params}
        keys_new = {key for key in params}

        keys_added = {key for key in keys_new if key not in keys_old}
        keys_removed = {key for key in keys_old if key not in keys_new}

        if len(keys_added) > 0:
            logger.info("{} parameter(s) added.".format(len(keys_added)))
            for key in keys_added: logger.info("    \"{}\": {}".format(key, params[key]))
        if len(keys_removed) > 0:
            logger.info("{} parameter(s) removed.".format(len(keys_removed)))
            for key in keys_removed: logger.info("    \"{}\"".format(key))

        # check for changes
        keys_remaining = {key for key in keys_old if key in keys_new}
        keys_changed = set()

        for key in keys_remaining:
            if params[key] != self.params[key]: keys_changed.add(key)

        if self.ticks == 0:
            keys_changed.add('funds'); keys_changed.add('logs_per_day'); keys_changed.add('log_dws')

        if "funds" in keys_changed:
            if params['funds'] == "0": logger.info("No maximum investment amount specified.")
            else: logger.info("Maximum investment amount set to {} {}.".format(params['funds'], self.base))
            self.params['funds'] = params['funds']
            keys_changed.remove('funds')
        if "logs_per_day" in keys_changed:
            if params['logs_per_day'] == "0": logger.info("Log updates turned off.")
            elif params['logs_per_day'] == "1": logger.info("Logs updating once per day.")
            else: logger.info("Logs updating {} times per day".format(params['logs_per_day']))
            self.params['logs_per_day'] = params['logs_per_day']
            keys_changed.remove('logs_per_day')
        if "log_dws" in keys_changed:
            if params['log_dws'] == "yes": logger.info("Deposit and withdrawal logs enabled.")
            else: logger.info("Deposit and withdrawal logs disabled.")
            self.params['log_dws'] = params['log_dws']
            keys_changed.remove('log_dws')

        if len(keys_changed) > 0:
            logger.info("{} parameter(s) changed.".format(len(keys_changed)))
            for key in keys_changed:
                logger.info("    \"{}\": {} -> {}".format(key, self.params[key], params[key]))
                self.params[key] = params[key]

    def get_new_candle(self):
        # Create a new candle from 1m candles
        candle_new = dict()
        for i in range(self.interval):
            candle_raw = self.candles_raw[- 1 - i]

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
                self.candles = shrink_list(self.candles, 5000)

    def get_positions(self):
        positions = {"asset": [self.asset, 0], "base": [self.base, 0]}
        try: data = client.get_account()["balances"]
        except Exception as e:
            logger.error("Error getting account balances.\n'{}'".format(e))
            return self.positions
        for i in range(len(data)):
            asset = data[i]["asset"]
            if asset not in {self.asset, self.base}: continue
            free = float(data[i]["free"])
            locked = float(data[i]["locked"])
            total = free + locked
            if asset == self.asset: positions['asset'][1] = total
            if asset == self.base: positions['base'][1] = total

        if self.ticks == 0:
            self.positions_init_ts = int(1000 * time.time())
            self.earliest_pending = int(self.positions_init_ts)

        return positions

    def update_f(self, p, apc):
        if apc == 0:
            if self.ticks != 1: return
            apc = p.price
        r = self.performance
        s = self.signal
        pos_f = self.positions_f
        pos_t = self.positions_t

        size = p.base + apc * p.asset
        rin = apc * p.asset / size
        sizeT = p.funds * (1 - s['rinTargetLast']) + apc * p.asset
        rinT = apc * p.asset / sizeT

        if self.ticks == 1: size_f = 1; size_t = 1
        else:
            size_f = pos_f['base'][1] + apc * pos_f['asset'][1]
            size_t = pos_t['base'][1] + apc * pos_t['asset'][1]
            if s['rinTarget'] == 0 and p.positionValue < self.min_order:
                profit = size_t - 1
                if profit >= 0: r['wSum'] += profit; r['W'] += 1; self.trades += 1
                if profit < 0: r['lSum'] += profit; r['L'] += 1; self.trades += 1
                if r['W'] != 0: r['w'] = r['wSum'] / r['W']
                if r['L'] != 0: r['l'] = r['lSum'] / r['L']
                size_t = 1

        base_f = (1 - rin) * size_f; base_t = (1 - rinT) * size_t
        asset_f = (rin / apc) * size_f; asset_t = (rinT / apc) * size_t

        pos_f['base'][1] = base_f; pos_t['base'][1] = base_t
        pos_f['asset'][1] = asset_f; pos_t['asset'][1] = asset_t

    def get_dws(self):
        diffasset_dw = 0; diffbase_dw = 0
        ts_last = self.candles[-2]['ts_end']
        if len(self.deposits_pending) == 0 and len(self.withdrawals_pending) == 0: self.earliest_pending = ts_last
        start_time = self.earliest_pending - 1000
        if self.ticks == 1: start_time = self.earliest_pending - 1000 * 60 * 60 * 24 * 7

        def process_d(deposit):
            amt = deposit['amount']
            diffasset = 0; diffbase = 0
            if self.params['log_dws'] == "yes":
                logger.warning("Deposit of {} {} detected.".format(fix_dec(amt), deposit['asset']))
            if deposit['asset'] == self.base: diffbase += amt
            else: diffasset += amt
            return diffasset, diffbase

        def process_w(withdrawal):
            amt = withdrawal['amount'] + withdrawal['transactionFee']
            diffasset = 0; diffbase = 0
            if self.params['log_dws'] == "yes":
                logger.warning("Withdrawal of {} {} detected.".format(fix_dec(amt), withdrawal['asset']))
            if withdrawal['asset'] == self.base: diffbase -= amt
            else: diffasset -= amt
            return diffasset, diffbase

        # get dws
        try:
            deposits = client.get_deposit_history(startTime = start_time)
            withdrawals = client.get_withdraw_history(startTime = start_time)

            # deal with differing formats
            if type(deposits) is dict:
                deposits = deposits['depositList']

            if type(withdrawals) is dict:
                withdrawals = withdrawals['withdrawList']

            for deposit in deposits:
                if 'asset' not in deposit:
                    deposit['asset'] = str(deposit['coin'])
                    deposit['creator'] = ''
                    deposit['amount'] = float(deposit['amount'])

            for withdrawal in withdrawals:
                if 'asset' not in withdrawal:
                    withdrawal['asset'] = str(withdrawal['coin'])
                    withdrawal['withdrawOrderId'] = ''
                    withdrawal['amount'] = float(withdrawal['amount'])
                    withdrawal['transactionFee'] = float(withdrawal['transactionFee'])

                if type(withdrawal['applyTime']) is str:
                    applyTime = time.strptime(withdrawal['applyTime'], '%Y-%m-%d %H:%M:%S')
                    applyTime = 1000 * timegm(applyTime)
                    withdrawal['applyTime'] = int(applyTime)
        except Exception as e:
            logger.error("Error getting deposits and withdrawals.\n'{}'".format(e))
            return 0, 0
        deposits = [d for d in deposits if d['asset'] in {self.asset, self.base}]
        withdrawals = [w for w in withdrawals if w['asset'] in {self.asset, self.base}]

        # add new pending trades to pending set
        # check for and process old pending trades that were filled
        for deposit in deposits:
            id = deposit['txId']
            if deposit['status'] < 1:
                self.deposits_pending.add(id)
                self.earliest_pending = start_time
                continue
            if id not in self.deposits_pending: continue
            if deposit['status'] > 0:
                diffasset, diffbase = process_d(deposit)
                diffasset_dw += diffasset
                diffbase_dw += diffbase
                self.deposits_pending.remove(id)
        for withdrawal in withdrawals:
            id = withdrawal['id']
            if withdrawal['status'] < 0:
                self.withdrawals_pending.add(id)
                self.earliest_pending = start_time
                continue
            if id not in self.withdrawals_pending: continue
            if withdrawal['status'] > -1:
                diffasset, diffbase = process_w(withdrawal)
                diffasset_dw += diffasset
                diffbase_dw += diffbase
                self.withdrawals_pending.remove(id)

        # skip the last section if it's the first tick
        if self.ticks == 1: return diffasset_dw, diffbase_dw

        # process dws received and completed in the last candle
        deposits = [d for d in deposits if d['insertTime'] > ts_last]
        deposits = [d for d in deposits if d['status'] > 0]
        withdrawals = [w for w in withdrawals if w['applyTime'] > ts_last]
        withdrawals = [w for w in withdrawals if w['status'] > -1]

        for deposit in deposits:
            id = deposit['txId']
            diffasset, diffbase = process_d(deposit)
            diffasset_dw += diffasset
            diffbase_dw += diffbase
        for withdrawal in withdrawals:
            id = withdrawal['id']
            diffasset, diffbase = process_w(withdrawal)
            diffasset_dw += diffasset
            diffbase_dw += diffbase

        return diffasset_dw, diffbase_dw

    def get_trades(self, p):
        diffasset_trad = 0; diffbase_trad = 0
        ts_last = self.candles[-2]['ts_end']
        l = self.last_order
        s = self.signal
        limit = int(ts_last)
        if self.ticks == 1: limit = self.positions_init_ts

        # Get trades
        try: trades = reversed(client.get_my_trades(symbol = self.pair, limit = 20))
        except Exception as e:
            logger.error("Error getting trade info.\n'{}'".format(e))
            return 0, 0, p.price
        trades = [t for t in trades if t['time'] > limit]

        # process trades
        if len(trades) > 0:
            str_out = "{} new trade(s) found.".format(len(trades))
            for trade in trades:
                str_out += "\n    {}".format(trade)
                qty = float(trade['qty'])
                price = float(trade['price'])
                if not trade['isBuyer']: qty *= -1
                diffasset_trad += qty
                diffbase_trad -= qty * price

        rbuy = s['rinTarget'] - s['rinTargetLast']
        rTrade = 0
        apc = 0
        if diffasset_trad != 0: apc = -diffbase_trad / diffasset_trad
        if l['amt'] != 0: rTrade = abs(diffasset_trad / l['amt'])
        if diffasset_trad > 0:
            log_amt = "{} {}".format(fix_dec(diffasset_trad), self.asset)
            log_size = "{} {}".format(fix_dec(diffasset_trad * apc), self.base)
            if l['type'] != "buy":
                logger.info("Manual buy detected.")
                rTrade = 0
            elif abs(rTrade - 1) > 0.1:
                logger.info("Buy order partially filled.")
            logger.warning("{} bought for {}.".format(log_amt, log_size))
        elif diffasset_trad < 0:
            log_amt = "{} {}".format(fix_dec(-diffasset_trad), self.asset)
            log_size = "{} {}".format(fix_dec(-diffasset_trad * apc), self.base)
            if l['type'] != "sell":
                logger.info("Manual sell detected")
                rTrade = 0
            elif abs(rTrade - 1) > 0.1:
                logger.info("Sell order partially filled.")
            logger.warning("{} sold for {}.".format(log_amt, log_size))

        if self.ticks == 1 or diffasset_trad != 0:
            s['rinTargetLast'] += rTrade * rbuy
            self.update_f(p, apc)

        return diffasset_trad, diffbase_trad, apc

    def get_dwts(self, p):
        # get deposits, withdrawals, and trades
        s = self.signal
        diffasset = round(self.positions['asset'][1] - self.positions_last['asset'][1], 8)
        diffbase = round(self.positions['base'][1] - self.positions_last['base'][1], 8)

        # get dws and trades
        diffasset_dw, diffbase_dw = self.get_dws()
        diffasset_trad, diffbase_trad, apc = self.get_trades(p)

        # get unknown changes
        diffasset_expt = round(diffasset_dw + diffasset_trad, 8)
        diffbase_expt = round(diffbase_dw + diffbase_trad, 8)
        diffasset_unkn = diffasset - diffasset_expt
        diffbase_unkn = diffbase - diffbase_expt

        # process unknown changes
        if self.params['log_dws'] == "yes":
            if diffasset_unkn > 0: logger.info("{} {} has become available.".format(fix_dec(diffasset_unkn), self.asset))
            elif diffasset_unkn < 0: logger.info("{} {} has become unavailable.".format(fix_dec(-diffasset_unkn), self.asset))
            if diffbase_unkn > 0: logger.info("{} {} has become available.".format(fix_dec(diffbase_unkn), self.base))
            elif diffbase_unkn < 0: logger.info("{} {} has become unavailable.".format(fix_dec(-diffbase_unkn), self.base))

        # set position and apc
        if apc == 0: apc = p.price
        if p.positionValue > self.min_order:
            if s['position'] != "long":
                s['position'] = "long"; s['apc'] = apc
        elif s['position'] != "none":
            s['position'] = "none"; s['apc'] = apc

        return

    def get_performance(self, p):
        if self.ticks == 1:
            self.candle_start = dict(self.candles[-1])
            self.positions_start = {key: value[:] for key, value in self.positions.items()}
        r = self.performance
        s = self.signal
        pos_f = self.positions_f
        pos_t = self.positions_t
        c_start = self.candle_start
        p_start = self.positions_start
        p_start_size = p_start['base'][1] + c_start['close'] * p_start['asset'][1]

        pfake_size = pos_f['base'][1] + p.price * pos_f['asset'][1]
        ptrade_size = pos_t['base'][1] + p.price * pos_t['asset'][1]

        r['bh'] = (p.price - c_start['close']) / c_start['close']
        r['change'] = (p.size - p_start_size) / p_start_size
        r['bProfits'] = pfake_size - 1
        r['aProfits'] = (1 + r['bProfits']) / (1 + r['bh']) - 1
        r['cProfits'] = ptrade_size - 1

        W = int(r['W']); w = float(r['w'])
        L = int(r['L']); l = float(r['l'])
        if r['cProfits'] >= 0: W += 1; wSum = r['wSum'] + r['cProfits']; w = wSum / W
        if r['cProfits'] < 0: L += 1; lSum = r['lSum'] + r['cProfits']; l = lSum / L
        r['be'] = W * w + L * l

    def log_update(self, p):
        r = self.performance

        hr = "~~~~~"
        tpd = float()
        if self.days != 0: tpd = self.trades / self.days
        winrate = float()
        if r['W'] + r['L'] != 0: winrate = r['W'] / (r['W'] + r['L'])
        header_1 = "{} {} {} {}".format(3 * hr, self.bot_name, self.version, 9 * hr)[:50]
        header_2 = "{} {} {} {}m {}".format(3 * hr, self.exchange.title(), self.pair, self.interval, 9 * hr)[:50]
        trades = "{} trades ({} per day)".format(int(self.trades), round(tpd, 2))
        currency = "{} {}".format(fix_dec(p.base), self.base)
        price = "{} {}".format(fix_dec(p.price), self.base)
        assets = "{} {}".format(fix_dec(p.asset), self.asset)
        assetvalue = "{} {}".format(fix_dec(p.positionValue), self.base)
        accountvalue = "{} {}".format(fix_dec(p.size), self.base)
        boteff = "{}% {},".format(round(100 * r['be'], 2), self.base)
        boteff += " {}% {}".format(round(100 * ((1 + r['be']) / (1 + r['bh'])) - 100, 2), self.asset)
        botprof = "{}% {},".format(round(100 * r['bProfits'], 2), self.base)
        botprof += " {}% {}".format(round(100 * ((1 + r['bProfits']) / (1 + r['bh'])) - 100, 2), self.asset)

        logger.info(header_1)
        logger.info(header_2)
        logger.info("Days running: {} | Trades completed: {}".format(round(self.days, 2), trades))
        logger.info("Currency: {} | Current price: {}".format(currency, price))
        logger.info("Assets: {} | Value of assets: {}".format(assets, assetvalue))
        logger.info("Value of account: {}".format(accountvalue))
        logger.info("    Win rate: {}%".format(round(100 * winrate, 2)))
        logger.info("    Wins: {} | Average win: {}%".format(r['W'], round(100 * r['w'], 2)))
        logger.info("    Losses: {} | Average loss: {}%".format(r['L'], round(100 * r['l'], 2)))
        logger.info("    Current profits: {}%".format(round(100 * r['cProfits'], 2)))
        logger.info("    Bot efficiency: {}".format(boteff))
        logger.info("Bot profits: {}".format(botprof))
        logger.info("Buy and hold: {}%".format(round(100 * r['bh'], 2)))

    def init(self, p):
        # Binance Pybot 20/100 SXS
        self.bot_name = "Binance Pybot"
        self.version = "0.2"
        logger.info("Analyzing the market...")

        # vars
        ma_lens = [[20, 100]]
        storage["ma_lens"] = ma_lens
        logger.info("Ready to start trading...")

    def strat(self, p):
        """ strategy / trading algorithm
        - Use talib for indicators
        - Talib objects require numpy.array objects as input
        - s stands for signal, rinTarget stands for 'ratio invested target'
        - Set s['rinTarget'] between 0 and 1. 0 is 0%, 1 is 100% invested
        """
        # vars
        s = self.signal
        ma_lens = storage["ma_lens"]
        num_sigs = len(ma_lens)
        close_data = numpy.array([c['close'] for c in self.candles])

        # get sigs
        SMAs = dict()
        class SMA:
            def __init__(self, ma_len):
                self.ma_len = ma_len
                self.arr = talib.SMA(close_data, timeperiod = ma_len)
                self.price = self.arr[-1]
                SMAs[ma_len] = self.price

        class SXS:
            def __init__(self, ma_len_pair):
                self.pair = ma_len_pair
                self.trend = "bear"
                if ma_len_pair[0] not in SMAs:
                    mas = SMA(ma_len_pair[0])
                self.mas = SMAs[ma_len_pair[0]]
                if ma_len_pair[1] not in SMAs:
                    mal = SMA(ma_len_pair[1])
                self.mal = SMAs[ma_len_pair[1]]
                if self.mas > self.mal: self.trend = "bull"

        sigs = list()
        for i in range(num_sigs):
            sig = SXS(ma_lens[i])
            sigs.append(sig)
        num_sigs = len(sigs)

        # set rinTarget
        nBulls = 0; nBears = 0
        s['rinTarget'] = 0
        for i in range(num_sigs):
            if sigs[i].trend == "bear": nBears += 1
            if sigs[i].trend == "bull":
                nBulls += 1
                s['rinTarget'] += 1 / num_sigs

    def ping(self):
        # check if its time for a new candle
        if (1000 * time.time() - self.candles_raw[-1]["ts_end"]) < 60000: return
        data = self.get_historical_candles(self.pair, "1m", 2)
        data_top = self.get_candle(data[0])

        # New raw candle?
        if data_top["ts_end"] != self.candles_raw[-1]["ts_end"]:
            self.candles_raw_unused += 1
            self.candles_raw.append(data_top)
            self.candles_raw = self.candles_raw[-2 * self.interval:]

        # New candle?
        if self.candles_raw_unused == self.interval:
            # Preliminary setup
            set_log_file()
            self.close_orders()
            self.update_vars()
            self.get_params()
            self.get_new_candle()

            self.positions_last = {key: value[:] for key, value in self.positions.items()}
            self.positions = self.get_positions()
            p = Portfolio(self.candles[-1], self.positions, float(self.params['funds']))
            self.get_dwts(p)
            self.get_performance(p)

            # Log output
            if self.params['logs_per_day'] == "0": self.next_log = self.days + 1
            if self.days >= self.next_log:
                self.log_update(p)
                self.next_log += 1 / float(self.params['logs_per_day'])

            # Trading strategy, buy/sell/other
            self.strat(p)
            self.bso(p)

ins = Instance(asset, base, interval_mins)
while True:
    ins.ping()
    time.sleep(0.5)
