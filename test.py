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

from pprint import pprint
import sys  # For simplicity, we'll read config file from 1st CLI param sys.argv[1]
import json
import logging
from datetime import datetime
from pathlib import Path
import re

import jwt
import requests
import msal


from exchangelib import (
    Configuration,
    OAUTH2,
    Account,
    OAuth2AuthorizationCodeCredentials,
    DELEGATE,
)

# Optional logging
# logging.basicConfig(level=logging.DEBUG)  # Enable DEBUG log for entire script
# logging.getLogger("msal").setLevel(logging.INFO)  # Optionally disable MSAL DEBUG logs

# config = json.load(open(sys.argv[1]))
config = {
    "authority": "https://login.microsoftonline.com/common",
    "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d753",  # thunderbird client_id
    "graph_scope": ["User.Read", "User.ReadBasic.All"],
    "exchange_scope": ["https://outlook.office.com/EWS.AccessAsUser.All"],
    "endpoint": "https://graph.microsoft.com/v1.0/me",
    "server": "outlook.office.com",
}


def get_msal_app() -> (
    tuple[msal.PublicClientApplication, msal.SerializableTokenCache, Path]
):
    cache = msal.SerializableTokenCache()
    cache_file = Path("mstokens.bin")
    if cache_file.exists():
        cache.deserialize(cache_file.read_text())
    app = msal.PublicClientApplication(
        config["client_id"], authority=config["authority"], token_cache=cache
    )

    accounts = app.get_accounts()
    # no accounts yet, starft device flow
    if not accounts:
        flow = app.initiate_device_flow(scopes=config["exchange_scope"])
        if "user_code" not in flow:
            raise ValueError(
                "Fail to create device flow. Err: %s" % json.dumps(flow, indent=4)
            )

        print(flow["message"])
        sys.stdout.flush()  # Some terminal needs this to ensure the message is shown

        # block until the user has authenticated
        token = app.acquire_token_by_device_flow(flow)

        if "access_token" not in token:
            raise ValueError(
                token.get("error")
                + token.get("error_description")
                + token.get("correlation_id")
            )

    if cache.has_state_changed:
        save_msal_cache(cache, cache_file)

    return app, cache, cache_file


def save_msal_cache(cache: msal.SerializableTokenCache, cache_file: Path):
    cache_file.touch(mode=0o600)  # create with safe permissions if new file
    cache_file.write_text(cache.serialize())


def get_token(scope: dict[str]):
    app, cache, cache_file = get_msal_app()
    accounts = app.get_accounts()

    # fetch the token from cache (and refresh it if necessary)
    print(
        f"Found account for {accounts[0]['username']} in cache. Trying to fetch token silently"
    )
    token = app.acquire_token_silent(
        scopes=scope,
        account=accounts[0],
        authority=None,
        claims_challenge=None,
        force_refresh=False,
    )

    if cache.has_state_changed:
        save_msal_cache(cache, cache_file)

    id_token = token["access_token"]
    # decode the OIDC id_token to get the user's email address
    algorithm = jwt.get_unverified_header(id_token).get("alg")
    decoded = jwt.decode(id_token, verify=False, options={"verify_signature": False})
    print("Got token:")
    print("  - aud: " + decoded["aud"])
    print("  - upn: " + decoded["upn"])
    print("  - scp: " + decoded["scp"])

    return token


def get_graph_token():
    return get_token(config["graph_scope"])


def get_exchange_token():
    return get_token(config["exchange_scope"])


graph_token = get_graph_token()
# Calling graph using the access token
graph_data = requests.get(  # Use token to call downstream service
    config["endpoint"],
    headers={"Authorization": "Bearer " + graph_token["access_token"]},
).json()
print("Graph API call result: %s" % json.dumps(graph_data, indent=2))

email = graph_data["userPrincipalName"]

exchange_token = get_exchange_token()

# now exchangelib:
creds = OAuth2AuthorizationCodeCredentials(access_token=exchange_token)
# creds = OAuth2AuthorizationCodeCredentials( access_token=OAuth2Token({'access_token': token}))
conf = Configuration(server=config["server"], auth_type=OAUTH2, credentials=creds)
a = Account(
    primary_smtp_address="bas.zoetekouw@surf.nl",
    config=conf,
    autodiscover=False,
    access_type=DELEGATE,
)
# print(a.root.tree())
print(
    a.calendar.filter(
        start__range=(
            datetime(2024, 5, 20, 0, 0, 0, tzinfo=a.default_timezone),
            datetime(2024, 5, 31, 23, 59, 59, tzinfo=a.default_timezone),
        )
    )[0]
)

print(a.delegates)

all_rooms=dict()
for roomlist in a.protocol.get_roomlists():
    print(roomlist.email_address)
    for room in a.protocol.get_rooms(roomlist.email_address):
        # parse room name for useful info
        # vergaderzaal 4.1 (18p, 75” lcd, conf. telefoon)
        match = re.search("^(\S+) +(\d.\d+) .+ +(\d+)p", room.name)
        room_type, room_num, room_pers = (
            match.groups() if match else ("unknown", "0.0", "?")
        )

        if room_type not in ('UTR', 'AMS'):
            continue

        if room_num in all_rooms:
            all_rooms[room_num]["groups"].add(roomlist.email_address)
        else:
            # parse room number and determine location
            try:
                room_floor, room_floornum = (int(i) for i in room_num.split("."))
            except ValueError:
                room_floor, room_floornum = ('?', '?')

            location = room_type

            this_room = {
                "description": room.name,
                "email": room.email_address.lower(),
                "type": room_type,
                "people": room_pers,
                "number": room_num,
                "floor": room_floor,
                "floor_subnum": room_floornum,
                "location": location,
                "groups": set([roomlist.email_address]),
            }
            all_rooms[room_num] = this_room

pprint(all_rooms)