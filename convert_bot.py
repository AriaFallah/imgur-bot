# To implement regular expressions to match image links
import re

# Interface to reddit API
import praw

# Interface to PostgresSQL database
# Database became kinda pointless when the bot
# switched to implementing the comment_stream method
# in place of get_comments
import psycopg2

# Private config variable of the bot
import botconfig

# To run try->catch block again
# Could have been easily done with a while loop
# But I wanted to learn how to make a python decorator
import retrydecorator

# Praw was throwing annoying warnings that cluttered up my testing
# So I got rid of them
import warnings
warnings.filterwarnings("ignore")

# To make requests to imgur and for reddit OAuth access token
import requests
import requests.auth

# Comment search configuration
MAXPOSTS = 1000
SUBREDDIT = "all"
REGEXP = re.compile("https?:\/\/gyazo\.com\/[a-z0-9]+")

# Configuration necessary for the bot initialization
CLIENT_ID = botconfig.CLIENT_ID
CLIENT_SECRET = botconfig.CLIENT_SECRET
USERNAME = botconfig.USERNAME
PASSWORD = botconfig.PASSWORD
USER_AGENT = botconfig.USER_AGENT

# Configuration necessary for imgur
IMGUR_CLIENT_ID = botconfig.IMGUR_CLIENT_ID

# Initialize praw and login to reddit
r = praw.Reddit(
    USER_AGENT, api_request_delay=2, cache_timeout=1)
r.set_oauth_app_info(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri="http://www.example.com/unused/redirect/uri")

# Connect to database and create table if it does not exist
psql = psycopg2.connect(database='convert_bot', user='aria')
cursor = psql.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS comments(id TEXT)")
psql.commit()


# Need to check whether the link is
# PNG, JPG, or GIF
def check_link(url):
    extensions = ['.png', '.jpg', '.gif']

    for extension in extensions:
        new_url = url + extension
        try:
            if requests.get(new_url).status_code == 404:
                print("\nFormat {0} is not valid".format(new_url))
            else:
                return new_url
        except Exception:
            return None


# Uploads a single image to imgur
def upload_to_imgur(url):
    image = check_link(url)
    if image is None:
        return None

    upload_url = 'https://api.imgur.com/3/image'
    headers = {"Authorization": "Client-ID {0}".format(IMGUR_CLIENT_ID)}
    data = {"image": image,
            "type": "URL"}

    print("\nUploading image from url ({0})...".format(image))
    reply = requests.post(upload_url, headers=headers, data=data)

    try:
        link = reply.json().get('data').get('link')
        if '.gif' in link:
            link += 'v'
    except ValueError:
        return None

    return link


# Gets the OAuth access token from reddit
# Courtesy of https://github.com/reddit/reddit/wiki/OAuth2-Quick-Start-Example
def get_access_token():
    client_auth = requests.auth.HTTPBasicAuth(
        CLIENT_ID,
        CLIENT_SECRET)
    post_data = {"grant_type": "password",
                 "username": USERNAME,
                 "password": PASSWORD}
    headers = {"User-Agent": USER_AGENT}
    response = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=client_auth, data=post_data, headers=headers)

    return response.json()['access_token']


# Uses regular expressions to check if comment has a link
# that needs reuploading if so returns the matching portion of the comment
def check_comment(comment):
    comment_id = comment.id

    # The database operations here aren't really necessary anymore
    # because comment_stream usually never fetches the same comments,
    # but there's no real reason to remove them

    # Skip if the comment has already been looked at before
    cursor.execute("SELECT * FROM comments WHERE id='%s'" % comment_id)
    if cursor.fetchone():
        return None

    # Enters unseen comments into the database
    cursor.execute("INSERT INTO comments (id) VALUES ('%s')" % comment_id)
    psql.commit()

    # Returns all occurences of gyazo links
    matches = REGEXP.findall(comment.body)
    if matches:
        return matches
    else:
        return None


# Uses OAuth access token to log into Reddit
def oauth_login():
    access_token = get_access_token()
    print("Logging in...")
    r.set_access_credentials({"identity", "submit"}, access_token)
    print("Login successful!")


# Replies to the comment with the non-direct-image link
# Uses a decorator to log in again if the OAuth access token expires
@retrydecorator.retry_on_error(2, oauth_login)
def reply_to_comment(comment, reply_body):
    comment.reply(reply_body)
    print("Replying to comment: %s\n" % comment.body)


# Loop that drives the bot
def loop_bot():
    oauth_login()

    counter = 0
    comments = praw.helpers.comment_stream(r, SUBREDDIT)
    # Delete everything from the database that is not
    # The most recent MAXNUMBER number of posts
    deletequery = "DELETE FROM comments WHERE id NOT IN" + \
        "(SELECT id FROM comments ORDER BY id DESC LIMIT %d)" % (MAXPOSTS)

    # For every comment in the comment stream
    for comment in comments:
        counter += 1
        link = None
        reply_body = ""

        # Every MAXPOSTS comments the database cleans itself up
        # To prevent it growing too large in size
        if counter % MAXPOSTS == 0:
            print ("%d comments processed!" % counter)
            cursor.execute(deletequery)

        # Check if the comment contains a link to reupload
        # Skip over if it does not
        matches = check_comment(comment)
        if not matches:
            continue

        # If there was more than one image in the post
        # Upload each image and add it to a new line of the reply body
        if len(matches) > 1:
            image_counter = 1
            for match in matches:
                link = upload_to_imgur(match)
                if link is not None:
                    reply_body += "Image {0}: ".format(image_counter) + \
                        link + '\n\n'
                image_counter += 1

        else:
            link = upload_to_imgur(matches[0])
            if link is not None:
                reply_body = link

        # Replies if links are not broken
        if not reply_body == "":
            reply_to_comment(comment, reply_body)

loop_bot()
