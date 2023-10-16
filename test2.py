"""
The configuration file would look like this:

{
    "authority": "https://login.microsoftonline.com/common",
    "client_id": "your_client_id",
    "scope": ["User.ReadBasic.All"],
        // You can find the other permission names from this document
        // https://docs.microsoft.com/en-us/graph/permissions-reference
    "endpoint": "https://graph.microsoft.com/v1.0/me"
        // You can find more Microsoft Graph API endpoints from Graph Explorer
        // https://developer.microsoft.com/en-us/graph/graph-explorer
}
You can then run this sample with a JSON configuration file:

    python sample.py parameters.json
"""
import pprint
import sys  # For simplicity, we'll read config file from 1st CLI param sys.argv[1]
import json
import logging

import requests
import msal


from exchangelib import (
    Configuration,
    OAUTH2,
    Account,
    DELEGATE,
    OAuth2AuthorizationCodeCredentials,
)


# set up cache
import os, atexit

from oauthlib.oauth2 import OAuth2Token

cache = msal.SerializableTokenCache()
if os.path.exists("my_cache.bin"):
    cache.deserialize(open("my_cache.bin", "r").read())
atexit.register(
    lambda: open("my_cache.bin", "w").write(cache.serialize())
    if cache.has_state_changed
    else None
)


# Optional logging
# logging.basicConfig(level=logging.DEBUG)  # Enable DEBUG log for entire script
# logging.getLogger("msal").setLevel(logging.INFO)  # Optionally disable MSAL DEBUG logs

# config = json.load(open(sys.argv[1]))
config = {
    "authority": "https://login.microsoftonline.com/common",
    "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d753",  # thunderbird client_id
    "scope": [
        "https://outlook.office.com/Calendars.Read",
        "https://outlook.office.com/Calendars.ReadBasic",
        "https://outlook.office.com/Calendars.Read.Shared",
        "https://outlook.office.com/EWS.AccessAsUser.All",
        "User.Read",
        "User.ReadBasic.All",
    ],
    #    "scope": ["EWS.AccessAsUser.All","User.ReadBasic.All"],
    "endpoint": "https://graph.microsoft.com/v1.0/me",
    "server": "outlook.office.com",
}

# Create a preferably long-lived app instance which maintains a token cache.
app = msal.PublicClientApplication(
    config["client_id"], authority=config["authority"], token_cache=cache
)

# The pattern to acquire a token looks like this.
token = None

# Note: If your device-flow app does not have any interactive ability, you can
#   completely skip the following cache part. But here we demonstrate it anyway.
# We now check the cache to see if we have some end users signed in before.
accounts = app.get_accounts()
if accounts:
    logging.info("Account(s) exists in cache, probably with token too. Let's try.")
    print("Pick the account you want to use to proceed:")
    for a in accounts:
        print(a["username"])
    # Assuming the end user chose this one
    chosen = accounts[0]
    # Now let's try to find a token in cache for this account
    token = app.acquire_token_silent(config["scope"], account=chosen)

if not token:
    logging.info("No suitable token exists in cache. Let's get a new one from AAD.")

    flow = app.initiate_device_flow(scopes=config["scope"])
    if "user_code" not in flow:
        raise ValueError(
            "Fail to create device flow. Err: %s" % json.dumps(flow, indent=4)
        )

    print(flow["message"])
    sys.stdout.flush()  # Some terminal needs this to ensure the message is shown

    # Ideally you should wait here, in order to save some unnecessary polling
    # input("Press Enter after signing in from another device to proceed, CTRL+C to abort.")

    token = app.acquire_token_by_device_flow(flow)  # By default it will block
    # You can follow this instruction to shorten the block time
    #    https://msal-python.readthedocs.io/en/latest/#msal.PublicClientApplication.acquire_token_by_device_flow
    # or you may even turn off the blocking behavior,
    # and then keep calling acquire_token_by_device_flow(flow) in your own customized loop.

if "access_token" not in token:
    print(token.get("error"))
    print(token.get("error_description"))
    print(token.get("correlation_id"))  # You may need this when reporting a bug
    sys.exit(1)

# Calling graph using the access token
graph_data = requests.get(  # Use token to call downstream service
    config["endpoint"],
    headers={"Authorization": "Bearer " + token["access_token"]},
).json()
print("Graph API call result: %s" % json.dumps(graph_data, indent=2))

email = graph_data["userPrincipalName"]

pprint.pprint(token)

# now exchangelib:
creds = OAuth2AuthorizationCodeCredentials(access_token=token)
#creds = OAuth2AuthorizationCodeCredentials( access_token=OAuth2Token({'access_token': token}))
conf = Configuration(server=config["server"], auth_type=OAUTH2, credentials=creds)
a = Account(
    primary_smtp_address=email,
    config=conf,
    autodiscover=False,
)
print(a.root.tree())
