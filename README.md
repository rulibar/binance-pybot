# binance-pybot
First attempt at a trading bot for Binance using Python. (binance-python package)

## Note
Currently working on core functionality. No changelog or versioning yet.

## How to run (Linux Mint Mate 19.2)
- Update system
$ sudo apt install python3-pip python3-setuptools python3-dev
$ sudo pip3 install python-binance
- See README on TA-Lib python wrapper GitHub
    https://github.com/mrjbq7/ta-lib/blob/master/README.md
- You need to install TA-Lib on your computer before the TA-Lib python wrapper
    will work.
- Locate the part on the README where it gives you a file to download and
    instructions to extract and install TA-Lib on Linux. Install TA-Lib
$ sudo pip3 install TA-Lib
- Now you will be able to import python-binance and talib
- Create a binance api key
- Open up binbot.py file, set api, api_secret, asset, base, and interval_mins
$ python3 binbot.py
