# ConvertToImgurBot

The bot scrapes reddit for non-direct-image links (Gyazo only currently) in comments, and reuploads them as direct image links to imgur in a reply to that comment.

# convert_bot_daemon.py

This runs in the background by using the python-daemon library. The documentation for that library is terrible. Anyone intending to make a daemon should start by looking [here](http://www.gavinj.net/2012/06/building-python-daemon-process.html). Some important things to note are that the database connection and praw need to be initialized inside of the run() block of the daemon. Moreover, make sure to mkdir /var/run/yourapp/ and set it's ownership from root to your own. Same process if you want to implement logging.
