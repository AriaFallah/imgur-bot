# To implement regular expressions to match image links
import re

# To log all unhandled exceptions
import sys

# Interface to reddit API
import praw

# Because the bot will be running in the background,
# it will log it's actions to a separate file to keep
# track of the bot's actions
import logging

# Interface to PostgresSQL database
import psycopg2

# Private config variable of the bot
import botconfig

# To make requests to imgur and for reddit OAuth access token
import requests
import requests.auth

# Turn into daemon using python-daemon
from daemon import runner

# Logging configuration
# To use the daemon, user must have permissions
# to write to the /var/... directory
FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOGFILE = "/var/log/bots/convert_bot.log"

logger = logging.getLogger("convert_bot log")
logger.setLevel(logging.INFO)
formatter = logging.Formatter(FORMAT)
handler = logging.FileHandler(LOGFILE)
handler.setFormatter(formatter)
logger.addHandler(handler)


# Function to rewrite how exceptions are output
# Causes them to be logged instead of output to stderr
def log_exceptions(exctype, value, traceback):
    logger.error("Uncaught exception!", exc_info=(exctype, value, traceback))

sys.excepthook = log_exceptions


class ConvertBot():
    def __init__(self):
        # Daemon configuration as required by
        # the daemon runner from python-daemon
        self.stdin_path = '/dev/null'
        self.stdout_path = '/dev/tty'
        self.stderr_path = '/dev/tty'
        # Directory /var/run/(app) must exist and must have permissions to it
        self.pidfile_path = '/var/run/bots/convert_bot.pid'
        self.pidfile_timeout = 5

        # Comment search configuration
        self.UPDATEFACTOR = 1000
        self.SUBREDDIT = "all"
        self.REGEXP = re.compile(r"https?:\/\/gyazo\.com\/[a-z0-9]+\b(?!\.)")

        # Configuration necessary for the bot initialization
        self.CLIENT_ID = botconfig.CLIENT_ID
        self.CLIENT_SECRET = botconfig.CLIENT_SECRET
        self.USERNAME = botconfig.USERNAME
        self.PASSWORD = botconfig.PASSWORD
        self.USER_AGENT = botconfig.USER_AGENT

        # Database config
        self.psql = None
        self.DB_NAME = botconfig.DB_NAME
        self.DB_USER = botconfig.DB_USER

        # Configuration necessary for imgur
        self.IMGUR_CLIENT_ID = botconfig.IMGUR_CLIENT_ID

    # Need to check whether the link is
    # PNG, JPG, or GIF
    def check_link(self, url):
        extensions = ['.png', '.jpg', '.gif']

        for extension in extensions:
            new_url = url + extension
            try:
                if requests.get(new_url).status_code == 404:
                    logger.info("Format {0} is not valid".format(new_url))
                else:
                    return new_url
            except Exception:
                return None

    # Uploads a single image to imgur
    def upload_to_imgur(self, url):
        image_url = self.check_link(url)
        if image_url is None:
            return None

        upload_url = 'https://api.imgur.com/3/image'
        headers = {
            "Authorization": "Client-ID {0}"
            .format(self.IMGUR_CLIENT_ID)}
        data = {
            "image": image_url,
            "type": "URL"}

        logger.info("Uploading image from url ({0})...".format(image_url))
        reply = requests.post(upload_url, headers=headers, data=data)

        try:
            link = reply.json().get('data').get('link')
            if '.gif' in link:
                link += 'v'
        except Exception:
            link = None

        return link

    # Gets the OAuth access token from reddit courtesy of
    # https://github.com/reddit/reddit/wiki/OAuth2-Quick-Start-Example
    def get_access_token(self):
        client_auth = requests.auth.HTTPBasicAuth(
            self.CLIENT_ID,
            self.CLIENT_SECRET)
        post_data = {
            "grant_type": "password",
            "username": self.USERNAME,
            "password": self.PASSWORD}
        headers = {"User-Agent": self.USER_AGENT}
        response = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=client_auth, data=post_data, headers=headers)

        return response.json()['access_token']

    # Uses regular expressions to check if comment has a link
    # that needs reuploading if so returns the matching portion of the comment
    def check_comment(self, comment):
        # Returns all occurences of gyazo links
        matches = self.REGEXP.findall(comment.body)
        if matches:
            return matches
        else:
            return None

    # Uses OAuth access token to log into Reddit
    def oauth_login(self):
        access_token = self.get_access_token()
        logger.info("Logging in...")

        self.reddit.set_access_credentials(
            {"identity", "submit"},
            access_token)

        logger.info("Login successful!")

    # Replies to the comment with the non-direct-image link
    # Uses a decorator to log in again if the OAuth access token expires
    def reply_to_comment(self, comment, reply_body):
        reply = None
        try_counter = 1
        success = False

        while not success and try_counter <= 2:
            try:
                try_counter += 1
                reply = comment.reply(reply_body)
                logger.info("Replying to comment: {0}".format(comment.body))
                success = True
            except Exception as e:
                logger.info("{0:s} exception! ".format(type(e).__name__))
                self.oauth_login()

        if not success:
            logger.info("Replying to comment failed!")

        return reply

    # Loop that drives the bot
    def run(self):
        # Connect to database and create tables if they do not exist
        self.psql = psycopg2.connect(
            database=self.DB_NAME,
            user=self.DB_USER)
        self.cursor = self.psql.cursor()

        # Initialize praw and login to reddit
        self.reddit = praw.Reddit(
            self.USER_AGENT,
            api_request_delay=1,
            cache_timeout=1)
        self.reddit.set_oauth_app_info(
            client_id=self.CLIENT_ID,
            client_secret=self.CLIENT_SECRET,
            redirect_uri="http://www.example.com/unused/redirect/uri")
        self.oauth_login()

        counter = 0
        comments = praw.helpers.comment_stream(
            self.reddit,
            self.SUBREDDIT,
            verbosity=0)

        # For every comment in the comment stream
        for comment in comments:
            link = None
            links = []
            counter += 1
            reply_body = ""
            image_counter = 0

            self.cursor.execute(
                "UPDATE convert_bot.totals "
                "SET amount = amount + 1, "
                             "last_updated = current_timestamp "
                "WHERE name = 'total_comments'")
            self.psql.commit()

            if counter % self.UPDATEFACTOR == 0:
                logger.info("{0} comments processed this session!".format(counter))

            # Check if the comment contains a link to reupload
            # Skip over if it does not
            matches = self.check_comment(comment)
            if not matches:
                continue

            self.cursor.execute(
                "INSERT INTO convert_bot.comments VALUES ('{0}', '{1}', '{2}', {3})"
                .format(
                    comment.id,
                    comment.author.name,
                    comment.submission.subreddit.display_name,
                    comment.created_utc))

            for match in matches:
                image_counter += 1
                self.cursor.execute(
                    "INSERT INTO convert_bot.originals (image_url, comment_id) VALUES ('{0}', '{1}')"
                    .format(
                        match,
                        comment.id))
                link = self.upload_to_imgur(match)
                if link is not None:
                    # Me nitpicking and not wanting a number
                    # included for the first element
                    if image_counter == 1:
                        reply_body += 'Image: {0} \n\n'.format(link)
                    else:
                        reply_body += 'Image {0}: {1} \n\n'.format(image_counter, link)
                    # We add the links to a list to defer their addition to the database
                    # This is because the reply_id does not exist yet
                    links.append((link, match))

            if not reply_body == "":
                reply = self.reply_to_comment(comment, reply_body)
                self.cursor.execute(
                    "INSERT INTO convert_bot.replies VALUES ('{0}', {1}, '{2}')"
                    .format(
                        reply.id,
                        reply.created_utc,
                        comment.id))

                for (link2, match) in links:
                    self.cursor.execute(
                        "SELECT id FROM convert_bot.originals "
                        "WHERE image_url = '{0}'".format(match))
                    original_id = self.cursor.fetchone()[0]

                    self.cursor.execute(
                        "INSERT INTO convert_bot.reuploads VALUES ('{0}', '{1}', {2})"
                        .format(
                            link2,
                            reply.id,
                            original_id))

            self.psql.commit()

bot = ConvertBot()
daemon_runner = runner.DaemonRunner(bot)

# This ensures that the logger file handle
# does not get closed during daemonization
daemon_runner.daemon_context.files_preserve = [handler.stream]
daemon_runner.do_action()
