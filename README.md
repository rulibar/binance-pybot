# Binance Pybot
A trading bot for Binance exchange using Python3 and packages python-binance and TA-Lib.
- Single-pair
- Non-margin
- Partial positions supported

## Note
Currently working on core functionality. No changelog or versioning yet.
Plan to release v0.1 soon. v0.x will be considered beta version with 1.0 being the first stable version.

## How to use
This depends on your operating system. For Ubuntu style distributions see the next section.
1. Make sure python3 is working on your system
2. Make sure you can import the python3 packages python-binance and TA-Lib
3. Create an API key on your Binance account, and add some funds
4. Enter your API key, trading pair, and tick size in the pybot.py file
5. Run the pybot.py file with python3

## How to use (on Ubuntu)
1. This should work on a vanilla system as long as you have a recent version. (early 2020)
2. Update your system:
```
sudo apt update -y && sudo apt upgrade -y
```
3. Python3 is install by default. Install pip3, python-binance, and other relevant packages.
```
sudo apt install python3-pip python3-setuptools python3-dev
sudo pip3 install python-binance
```
4. Download and install TA-Lib on your system using the instructions on their GitHub.
    - https://github.com/mrjbq7/ta-lib/blob/master/README.md
    - TA-Lib stands for technical analysis library, includes technical analysis indicators
    - TA-Lib must be installed on your computer to run the TA-Lib python package
    - Download the tar, extract, and install it based on the instructions
5. Install TA-Lib on pip3
```
sudo pip3 install TA-Lib
```
6. Now you should be able to run the bot. You just need to set up your configuration.
    - Create an API key on your Binance account
    - Decide which asset/base pair to trade (Ex: ETH/BTC)
    - Add funds to your Binance account
    - Enter your API key, pick your asset and base, and choose tick size in pybot.py file
    - You may want to edit the parameters in the config.txt file
7. Run the bot:
```
python3 pybot.py
```
8. A folder called logs will be created. In here you can find the log files to see the progress of your bot.

### Parameter ranges:
Interval mins - Between 5 and 120. Anything else is experimental
Asset/base - All should be supported if they exist on Binance
Funds - Should be zero or greater. Zero means no limit
Logs per day - Should be zero or greater. Zero means no logs
Log dws - Should be 'yes' or 'no'

## How to run long-term instances
To run long-term instances the bot must be run in daemon on a reliable 24/7 server, like an AWS cloud server.
1. Configure the bot as usual and transfer it over to your permanent server
2. Run the bot in daemon mode by using the ampersand
    - You may want to change the name of pybot.py if you intend to run more than one bot (to differentiate between them)
```
python3 pybot.py &
```
3. The bot will be ran in daemon mode and will save logs in the logs folder
4. Run a search to see all of the running python scripts and get their process ids
```
ps -ef | grep ".py"
```
5. When you are ready to kill a bot, use the kill command
```
kill process_id
Ex: kill 1234
```

## How to create strategies
To create strategies you must modify the Instance.init and Instance.strat methods
- Instance.init runs right when you first run the code, and initializes the strategy
- Instance.strat runs every time there's a new tick
- In Instance.strat you set the variable s['rinTarget'] between 0 and 1. 0 means don't hold any assets. 1 means go all in.
- You can access portfolio data with self.portfolio
- You can access candle data with self.candles or self.candles[-1] for the most recent candle
- You can use TA-Lib indicators. Research python TA-Lib for more info.
- TA-Lib indicators require numpy.array objects as their input and return numpy.array objects
- The last element of a TA-Lib object is the most recent
- The default strategy is an SXS strategy, where two SMAs, long and short, cross over each other to give buy and sell signals
- See the default strategy for more info about how to access candle data and use TA-Lib indicators to set s['rinTarget']
