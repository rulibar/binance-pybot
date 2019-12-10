"""
Binance Trading Bot

/Error 1:
When the bot starts, the last candle was around 27 minutes ago. Next in 3 mins.
When the bot start, portfolio is calculated.
If a trade occurred before portfolio was calculated, it will be seen by the bot,
but the corresponding change in portfolio won't be seen.
A: I should probably find a way to not import trades on the first candle unless
it happened since I imported my portfolio.

Fix:
/- Put get_positions inside the new candle algorithm in ping
    So portfolios aren't imported until right before dwts happens.
    And when portfolios are saved the timestamp is saved anyways.

/Error 2:
When depositing funds the bot will see the order before the funds are deposited
in the account while it's waiting for confirmations. This causes unkn balance
changes because the detection and the reception of the funds occur at different
times.
This would be less of an issue on a long timeframe but still could occur.

Fix:
/- Save the timestamp of the last deposit (or the start time if no deposits yet)
/- Import deposits since last deposit, filter out incomplete and irrelevant ones
/- If there is a relevant completed deposit then process it

/Error 3:
When withdrawing funds the the bot doesn't include the fee in the amount.

Fix:
/- Don't just take the amount. Take 'amount' + 'transactionFee'
/- Binance reports the funds withdrawn immediately so Error 2 doesn't happen for
withdrawals.

/Error 4:
Now when you deposit funds the bot will not see the deposit if the deposit was
pending at the time the bot was started

Fix:
/- Instead of setting ts_lastd to ts
/- get all dws in the past week
/- filter out all that are completed, then take the ts of the earliest,
subtract 1s, and set that as your ts_lastd
    - This way, when the bot imports ds it will go back far enough to include
    pending ds

/Error 5:
When a dw is processed, it will continue to be processed on future candles.
This is because self.lastd is not updated. If there are no pending orders, then
earliest gets set to self.lastd and previously processed orders are processed
again.

Fix:
/- Fixed by fixing Error 6

/Error 6:
If two deposits are initiated at around the same time. The deposit that was
initiated second might actually be processed first. In this case, the second
deposit would be processed again and again until the unprocessed deposit is
also processed.

- This method clearly isn't working. I need to rethink this.
- It appears I need to track all dws processed
- If a dw needs to be processed, I can check if it's already been processed by
    checking the record
- On each candle, I can get earliest from the earliest pending order
- If no pending orders, then all orders are processed, so you know the only
    relevant orders would have been processed in the last candle

- I simply don't know what time the order status went from 0 to 1
- Maybe the best thing to do is track all pending orders as well, so on each
    candle I can check if the pending orders have been filled

/- On start, get all dws from past week, remove completed dws
    (since portfolio was just barely calculated we only care about pending)
/- Create dicts to track dws, key is orderId, value is dw
/- Each candle I am interested in
    - Are there any new pending orders?
    - Have any of the previous pending orders been completed?
/- So I store a set of pending orders
/- Each candle I import trades from earliest pending
/- Check set of pending to see if any pending have been processed
    /- If so, output message and updated expected chng
    /- Update dict entry
    /- Remove from pending set
/- Remove all dws that didn't happen in the last candle
/- Remaining are new orders
/    - Add dict entry
/    - Add to pending set if not completed
/    - Otherwise, process

/- So I need to save self.deposits, self.deposits_pending, self.withdrawals,
self.withdrawals_pending, self.earliest_pending

Changes:
- In get_historical_candles_method, take the Exception and output it
- Calculate ticks and days in ping instead of in tick
- Total re-do of get_dwts method. Now imports dwts and compares expected change
    to actual change
- Stores information about deposits and withdrawals
- Fixed a bug with missing bracket on raw candles
- Update comments/formatting

"""

from binance.client import Client
from datetime import datetime
import time

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

        #self.ts_lastd = 0
        #self.ts_lastw = 0

        self.deposits = dict()
        self.withdrawals = dict()
        self.deposits_pending = set()
        self.withdrawals_pending = set()
        self.earliest_pending = 0

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

    def init(self):
        print("~~ Init ~~")

    def tick(self):
        print("~~ Tick ~~")
        print(self.candles[-1])
        print(self.positions)

    def get_dwts(self, asset_diff, base_diff):
        """#
        # get all pending dws from the last week, find the earliest
        ts_end = self.candles[-2]['ts_end']
        ts0 = 1000*time.time()
        deposits = client.get_deposit_history(startTime = ts - 1000*60*60*24*7)['depositList']
        withdrawals = client.get_withdraw_history(startTime = ts - 1000*60*60*24*7)['withdrawList']
        deposits = [d for d in deposits if d['asset'] in {asset, base}]
        withdrawals = [w for w in withdrawals if w['asset'] in {asset, base}]

        deposits_pending = [d for d in deposits if d['status'] < 1]
        withdrawals_pending = [w for w in withdrawals if w['status'] < 4]

        earliest = ts
        for dw in deposits_pending + withdrawals_pending:
            if dw['insertTime'] < earliest: earliest = dw['insertTime'] - 1000
        ts1 = 1000*time.time()
        print("2", ts1 - ts0)
        ts0 = ts1
        # get all dws as far back as necessary to get all pending dws
        #deposits = client.get_deposit_history(startTime = earliest)['depositList']
        #withdrawals = client.get_withdraw_history(startTime = earliest)['withdrawList']
        #deposits = [d for d in deposits if d['asset'] in {asset, base}]
        #withdrawals = [w for w in withdrawals if w['asset'] in {asset, base}]

        for deposit in deposits: print("~", deposit)
        for withdrawal in withdrawals: print("~", withdrawal)

        deposits = [d for d in deposits if d['insertTime'] > earliest]
        withdrawals = [w for w in withdrawals if w['applyTime'] > earliest]

        for deposit in deposits: print("~", deposit)
        for withdrawal in withdrawals: print("~", withdrawal)

        assetdiff_exp = 0.0
        basediff_exp = 0.0

        # process dws
        ts1 = 1000*time.time()
        print("3", ts1 - ts0)
        ts0 = ts1
        if len(deposits) > 0:
            print("{} new deposit(s) found.".format(len(deposits)))
            for deposit in deposits:
                print("~", deposit)
                if deposit['status'] < 1: continue
                amt = deposit['amount']
                if deposit['asset'] == base: basediff_exp += amt
                else: assetdiff_exp += amt
        if len(withdrawals) > 0:
            print("{} new withdrawal(s) found.".format(len(withdrawals)))
            for withdrawal in withdrawals:
                print("~", withdrawal)
                if withdrawal['status'] < 4: continue
                #self.ts_lastw = withdrawal['']
                amt = withdrawal['amount'] + withdrawal['transactionFee']
                if withdrawal['asset'] == base: basediff_exp -= amt
                else: assetdiff_exp -= amt
        """

        print(self.ticks, self.days)

        # get end of previous candle, initialize vars
        ts_end = self.candles[-2]['ts_end']
        assetdiff_exp = 0.0
        basediff_exp = 0.0
        #ts = self.ts_lastd
        ts = self.earliest_pending
        ts0 = 1000*time.time()

        ts1 = 1000*time.time()
        print("1", ts1 - ts0)
        ts0 = ts1

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

            print("self.deposits: ", self.deposits)
            print("self.withdrawals: ", self.withdrawals)
            print("self.earliest_pending: ", self.earliest_pending)
        else: # not first tick
            # get all dws starting from 1 s before the earliest pending dw
            deposits = client.get_deposit_history(startTime = ts - 1000)['depositList']
            withdrawals = client.get_withdraw_history(startTime = ts - 1000)['withdrawList']
            # filter for asset
            deposits = [d for d in deposits if d['asset'] in {asset, base}]
            withdrawals = [w for w in withdrawals if w['asset'] in {asset, base}]

            for deposit in deposits: print("~", deposit)
            for withdrawal in withdrawals: print("~", withdrawal)

            # check if pending dws have been completed then process them
            for deposit in deposits:
                id = deposit['txId']
                if id in self.deposits_pending:
                    if deposit['status'] > 0:
                        print("Deposit processed")
                        amt = deposit['amount']
                        if deposit['asset'] == base: basediff_exp += amt
                        else: assetdiff_exp += amt
                        self.deposits[id] = deposit
                        self.deposits_pending.remove(id)
            for withdrawal in withdrawals:
                id = withdrawal['id']
                if id in self.withdrawals_pending:
                    if withdrawal['status'] > 3:
                        print("Withdrawal processed")
                        amt = withdrawal['amount'] + withdrawal['transactionFee']
                        if withdrawal['asset'] == base: basediff_exp -= amt
                        else: assetdiff_exp -= amt
                        self.withdrawals[id] = withdrawal
                        self.withdrawals_pending.remove(id)

            # check if any dws have been added in the last candle
            deposits = [d for d in deposits if d['insertTime'] > ts_end]
            withdrawals = [w for w in withdrawals if w['applyTime'] > ts_end]

            # add new dws to pending if pending or process them
            for deposit in deposits:
                print("~", deposit)
                id = deposit['txId']
                self.deposits[id] = deposit
                if deposit['status'] < 1: self.deposits_pending.add(id)
                else:
                    print("Deposit processed")
                    amt = deposit['amount']
                    if deposit['asset'] == base: basediff_exp += amt
                    else: assetdiff_exp += amt
            for withdrawal in withdrawals:
                print("~", withdrawal)
                id = withdrawal['id']
                self.withdrawals[id] = withdrawal
                if withdrawal['status'] < 0: self.withdrawals_pending.add(id)
                else:
                    print("Withdrawal processed")
                    amt = withdrawal['amount'] + withdrawal['transactionFee']
                    if withdrawal['asset'] == base: basediff_exp -= amt
                    else: assetdiff_exp -= amt

            print("self.deposits: ", self.deposits)
            print("self.withdrawals: ", self.withdrawals)
            print("self.earliest_pending: ", self.earliest_pending)

        # Get trades
        ts1 = 1000*time.time()
        print("4", ts1 - ts0)
        ts0 = ts1
        trades = list(reversed(client.get_my_trades(symbol = self.pair, limit = 20)))
        for i in range(len(trades)):
            trade = trades[i]
            if trade['time'] < ts_end:
                trades = trades[:i]
                break

        # process trades
        ts1 = 1000*time.time()
        print("5", ts1 - ts0)
        ts0 = ts1
        if len(trades) > 0:
            print("{} new trade(s) found.".format(len(trades)))
            for trade in trades:
                print("~", trade)
                qty = float(trade['qty'])
                price = float(trade['price'])
                if not trade['isBuyer']: qty *= -1
                assetdiff_exp += qty
                basediff_exp -= qty * price

        assetdiff_unkn = round(asset_diff - assetdiff_exp, 8)
        basediff_unkn = round(base_diff - basediff_exp, 8)

        print("assetdiff_exp", assetdiff_exp)
        print("asset_diff", asset_diff)
        print("basediff_exp", basediff_exp)
        print("base_diff", base_diff)
        print("assetdiff_unkn", assetdiff_unkn)
        print("basediff_unkn", basediff_unkn)

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
            print("positions", positions)
            print("self.positions", self.positions)
            asset_diff = positions[self.asset] - self.positions[self.asset]
            base_diff = positions[self.base] - self.positions[self.base]
        except:
            #asset_diff = 0
            #base_diff = 0
            """ts = round(1000*time.time())

            deposits = client.get_deposit_history(startTime = ts - 1000*60*60*24)['depositList']
            #withdrawals = client.get_withdraw_history(startTime = ts - 1000*60*60*24)['withdrawList']

            deposits = [d for d in deposits if d['status'] == 0]
            if len(deposits) > 0:
                earliest = ts
                print("Pending deposits:")
                for deposit in deposits:
                    print("~", deposit)
                    if deposit['insertTime'] < earliest: earliest = deposit['insertTime']

            #for withdrawal in withdrawals:
            #    print("~", withdrawal)

            self.ts_lastd = earliest - 1000
            self.ts_lastw = ts"""
            ts = round(1000*time.time())
            #self.ts_lastd = ts
            #self.ts_lastw = ts
            self.earliest_pending = ts
            return positions

        # check for dwts before returning positions
        self.get_dwts(asset_diff, base_diff)
        return positions

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
            self.tick()

ins = Instance(asset, base, interval_mins)
ins.init()

while True:
    ins.ping()
    time.sleep(2)
