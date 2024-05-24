#!/usr/bin/python3
from __future__ import annotations

import dataclasses
import sys
from enum import Enum, StrEnum
from pathlib import Path

from pprint import pprint
import logging
import datetime
import dateutil.parser
import time

import jwt
import pytz
import json
import re

import msal, msal.authority
import platformdirs

import exchangelib
from exchangelib import (
    Configuration,
    OAUTH2,
    Account,
    OAuth2AuthorizationCodeCredentials,
    DELEGATE,
)



# from http://stackoverflow.com/questions/9868653/find-first-sequence-item-that-matches-a-criterium
def findfirst(items, pred):
    return next((i for i in enumerate(items) if pred(i[1])), (None, None))


class JSONAgendaEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        elif isinstance(o, datetime.date):
            return o.strftime("%Y-%m-%d")
        else:
            return json.JSONEncoder.default(self, o)


DEFAULT_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"  # thunderbird client_id
DEFAULT_TIMEZONE = "Europe/Amsterdam"
DEFAULT_CACHE_FILE = Path(platformdirs.user_cache_dir()) / Path("net.zoetekouw.surfchange.tokens.bin")
#DEFAULT_EXCHANGE_SCOPE = ["https://outlook.office.com/EWS.AccessAsUser.All"]
DEFAULT_EXCHANGE_SCOPE = [
    "https://outlook.office.com/Calendars.Read",
    "https://outlook.office.com/Calendars.Read.Shared",
    "https://outlook.office.com/User.ReadBasic.All",
]
DEFAULT_GRAPH_SCOPE = ["User.Read", "User.ReadBasic.All"]
DEFAULT_EWS_SERVER = "outlook.office.com"


# see https://learn.microsoft.com/en-us/exchange/client-developer/web-service-reference/myresponsetype
class ResponseType(StrEnum):
    UNKNOWN = "Unknown"
    ORGANIZER = "Organizer"
    TENTATIVE = "Tentative"
    ACCEPT = "Accept"
    DECLINE = "Decline"
    NORESPONSE = "NoResponseReceived"



@dataclasses.dataclass
class Attendee:
    name: str|None = None
    email: str|None = None
    response: ResponseType = ResponseType.UNKNOWN

    @staticmethod
    def from_ews(ews_attendee: exchangelib.Attendee):
        return Attendee(
            name=ews_attendee.mailbox.name,
            email=ews_attendee.mailbox.email_address,
            response=ResponseType(ews_attendee.response_type)
        )

    def __hash__(self):
        return hash(self.email)

    def __eq__(self, other):
        return self.email == other.email


# token cache that automatically saves to file on changes
class SurfTokenCache(msal.SerializableTokenCache):
    def __init__(self, cache_file: Path | str = DEFAULT_CACHE_FILE):
        self.cache_file = Path(cache_file)
        super(SurfTokenCache, self).__init__()
        try:
            self.load()
        except FileNotFoundError:
            # no cache file yet, create one
            self.save()

    def save(self):
        # make sure permissions are safe, also for new files
        self.cache_file.touch()
        self.cache_file.chmod(0o600)
        self.cache_file.write_text(self.serialize())

    def load(self, cache_file=None):
        if cache_file is not None:
            self.cache_file = cache_file
        self.deserialize(self.cache_file.read_text())

    def add(self, *args):
        super(SurfTokenCache, self).add(*args)
        if self.has_state_changed:
            self.save()

    def modify(self, *args):
        super(SurfTokenCache, self).modify(*args)
        if self.has_state_changed:
            self.save()


class SurfAgenda:
    def __init__(
        self,
        client_id=DEFAULT_CLIENT_ID,
        cache_file=DEFAULT_CACHE_FILE,
        tz=DEFAULT_TIMEZONE,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing SurfAgenda")

        self._email = None
        self.client_id = client_id
        self.scopes = DEFAULT_EXCHANGE_SCOPE + DEFAULT_GRAPH_SCOPE

        self.tz = pytz.timezone(tz)

        self._msal_cache = None
        if cache_file is None:
            self._msal_cache = msal.TokenCache() # in-memory cache
        else:
            self._msal_cache = SurfTokenCache(cache_file=cache_file)

        self._msal_app = self._get_msal_app()
        self.credentials = None

        self._rooms = {"updated": 0, "data": None}

    def _get_msal_app(self) -> msal.PublicClientApplication:
        # try to read cache
        app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority="https://login.microsoftonline.com/surf.nl",
            token_cache=self._msal_cache,
        )
        return app

    @property
    def email(self):
        if self._email is None:
            accounts = self._msal_app.get_accounts()
            if accounts:
                self._email = accounts[0]["username"]
        return self._email

    def authenticate(self):
        app = self._msal_app
        accounts = app.get_accounts()
        if not accounts:
            # no accounts yet, start device code flow
            flow = app.initiate_device_flow(scopes=self.scopes)
            if "user_code" not in flow:
                raise ValueError("Fail to create device code flow. Err: %s"
                                 % json.dumps(flow, indent=4))

            # print URL and device code to log in to Microsoft
            print(flow["message"])
            sys.stdout.flush()

            # block until the user has authenticated in the browser
            token = app.acquire_token_by_device_flow(flow)

            if "access_token" not in token:
                raise ValueError(
                    token.get("error")
                    + token.get("error_description")
                    + token.get("correlation_id")
                )

        self._msal_app = app

    def get_token(self, scopes: list[str]):
        self.authenticate()
        accounts = self._msal_app.get_accounts()

        # fetch the token from cache (and refresh it if necessary)
        print(
            f"Found account for {accounts[0]['username']} in cache. Trying to fetch token silently"
        )
        token = self._msal_app.acquire_token_silent_with_error(
            scopes=scopes,
            account=accounts[0],
            authority=None,
            claims_challenge=None,
            force_refresh=False,
        )

        id_token = token["access_token"]
        # decode the OIDC id_token to get the user's email address
        algorithm = jwt.get_unverified_header(id_token).get("alg")
        decoded = jwt.decode(id_token, verify=False, options={"verify_signature": False})
        print("Got token:")
        print("  - alg: " + algorithm)
        print("  - aud: " + decoded["aud"])
        print("  - upn: " + decoded["upn"])
        print("  - scp: " + decoded["scp"])

        return token
    def get_EWS_token(self):
        return self.get_token(DEFAULT_EXCHANGE_SCOPE)

    def get_graph_token(self):
        return self.get_token(DEFAULT_GRAPH_SCOPE)




    def _get_account(self, email=None):
        if email is None:
            email = self.email

        # now exchangelib:
        creds = OAuth2AuthorizationCodeCredentials(access_token=self.get_EWS_token())
        # creds = OAuth2AuthorizationCodeCredentials( access_token=OAuth2Token({'access_token': token}))
        conf = Configuration(server=DEFAULT_EWS_SERVER, auth_type=OAUTH2, credentials=creds)
        account = Account(
            primary_smtp_address=email,
            config=conf,
            autodiscover=False,
            access_type=DELEGATE,
        )
        return account

    @staticmethod
    def _parse_date(date):
        if isinstance(date, datetime.date):
            return date
        if isinstance(date, datetime.datetime):
            return date.date()

        if date == "today" or date == "vandaag":
            return datetime.date.today()
        if date == "tomorrow" or date == "morgen":
            return datetime.date.today() + datetime.timedelta(days=1)
        if date == "dayaftertomorrow" or date == "dat" or date == "overmorgen":
            return datetime.date.today() + datetime.timedelta(days=2)
        if date[0] == "+":
            numdays = int(date[1:])
            return datetime.date.today() + datetime.timedelta(days=numdays)

        return dateutil.parser.parse(date, dayfirst=True, yearfirst=False)

    def get_agenda(self, dt_start: datetime.datetime, dt_stop: datetime.datetime, email=None):
        self.logger.debug(
            "get_agenda for {}, from {} to {}".format(email, dt_start, dt_stop)
        )
        account = self._get_account(email)

        assert isinstance(dt_start, datetime.datetime) and isinstance(
            dt_stop, datetime.datetime
        )
        if dt_stop < dt_start:
            return list()

        def agenda_sort_key(a: exchangelib.EWSDateTime|exchangelib.EWSDate):
            s = a.start
            if isinstance(s, exchangelib.EWSDate) or isinstance(s, datetime.date):
                return datetime.datetime.combine(s, datetime.time.min)
            elif isinstance(a, exchangelib.EWSDateTime) or isinstance(s, datetime.datetime):
                return datetime.datetime(s)
            raise ValueError("Unknown type")

        agenda_items = account.calendar.view(
            exchangelib.EWSDateTime.from_datetime(dt_start),
            exchangelib.EWSDateTime.from_datetime(dt_stop),
        )
        agenda_items = sorted(agenda_items, key=agenda_sort_key)

        meetings = list()
        for item in agenda_items:
            # print("===========================")
            # print(item)

            is_private = item.sensitivity.lower() == "private"

            attendees = list()
            if not is_private:
                # note that optional_attendees and required_attendees might be None
                attendees = set(
                    Attendee.from_ews(p) for p in (item.optional_attendees or []) + (item.required_attendees or [])
                )

            resources = list()
            if not is_private:
                # note that optional_attendees and required_attendees might be None
                resources = set(Attendee.from_ews(p) for p in (item.resources or []))

            organizer = Attendee()
            if item.organizer and not is_private:
                organizer = Attendee(item.organizer.name, item.organizer.email_address, ResponseType.ORGANIZER)

                # this corrects the responsetype;
                # works because Attendee equality only considers email addresses
                if organizer in attendees:
                    attendees.remove(organizer)
                attendees.add(organizer)

            def ewstime2datetime(t: exchangelib.EWSDate|exchangelib.EWSDateTime, tz: datetime.tzinfo = None):
                # note that EWSDate is a subclass of datetime.date, and EWSDateTime is a subclass of datetime
                if isinstance(t, datetime.date):
                    return datetime.datetime.combine(item.start, datetime.time.min, tzinfo=tz)
                elif isinstance(t, datetime.datetime):
                    return datetime.datetime(t).astimezone(tz)
                raise ValueError("Unknown type")

            start = ewstime2datetime(item.start, self.tz)
            end = ewstime2datetime(item.end, self.tz)

            # TODO: handle stringification during json serialization
            meeting = dict(
                {
                    "start": start,
                    "end": end,
                    "time_start": start.strftime("%H:%M"),
                    "time_end": end.strftime("%H:%M"),
                    "date_start": start.strftime("%Y-%m-%d"),
                    "date_end": end.strftime("%Y-%m-%d"),
                    "duration": end-start,
                    "all_day": item.is_all_day,
                    "organizer": organizer,
                    "online": item.is_online_meeting,
                    "subject": (item.subject if not is_private else "Private appointment"),
                    "description": (item.text_body if not is_private else ""),
                    "location": item.location if not is_private else "Undisclosed",
                    "attendees": attendees,
                    "resources": resources,
                    "my_response": ResponseType(item.my_response_type),
                }
            )
            meetings.append(meeting)
            self.logger.debug("  - {start}-{end}: {subject}".format(**meeting))

        # this probably is already sorted, but let's just make sure
        meetings = sorted(meetings, key=lambda a: a["start"])

        return meetings

    def get_agenda_for_days(self, date_start: datetime.date, date_stop: datetime.date, email=None):
        assert isinstance(date_start, datetime.date) and isinstance(
            date_stop, datetime.date
        )

        dt_start = datetime.datetime.combine(
            date_start, datetime.time(hour=0, minute=0, second=0, tzinfo=self.tz)
        )
        dt_stop = datetime.datetime.combine(
            date_stop, datetime.time(hour=23, minute=59, second=59, tzinfo=self.tz)
        )

        return self.get_agenda(email=email, dt_start=dt_start, dt_stop=dt_stop)

    def get_agenda_for_day(self, email=None, date=datetime.date.today()):
        realdate = self._parse_date(date)
        assert isinstance(realdate, datetime.date)
        return self.get_agenda_for_days(email=email, date_start=realdate, date_stop=realdate), realdate

    def get_availability(self, email, date=datetime.date.today()):
        self.logger.info("Fetching availability for %s on %s", email, date.isoformat())

        agenda, realdate = self.get_agenda_for_day(email, date)
        now = datetime.datetime.now(tz=self.tz)

        self.logger.info("Now is %s", now.isoformat())
        self.logger.debug(
            "Agenda for %s: %s",
            email,
            json.dumps(agenda, sort_keys=True, indent=4, cls=JSONAgendaEncoder),
        )
        # debugging
        # now = now.replace(hour=10,minute=15)

        # walk through list to find current/next meeting
        index_next, entry_next = findfirst(agenda, lambda a: a["end"] > now)
        self.logger.debug(
            "Next is {}: {}".format(
                index_next, json.dumps(entry_next, cls=JSONAgendaEncoder)
            )
        )

        # three possibilities now:
        # (1) no further meetings today (nothing found, None returned)
        # (2) room is currently free (so next meeting hasn't started)
        # (3) room is currently occupied (next meeting has started)
        if index_next is None:
            self.logger.debug("fork (1)")
            available = True
            next_dt = None
            txt = "vrij"
        elif entry_next["start"] >= now:
            self.logger.debug("fork (2)")
            available = True
            next_dt = entry_next["start"]
            if next_dt.date() == now.date():
                txt = "vrij tot {}".format(next_dt.strftime("%H:%M"))
            else:
                txt = "vrij"
        else:
            self.logger.debug("fork (3)")
            available = False
            # find next available slot by checking for a gap between meeting of at least 5 minutes
            # keep track of latest endtime of all relevant meetings
            last = entry_next["end"]
            for i, a in enumerate(agenda[index_next:-2], index_next):
                if agenda[i + 1]["start"] - last > datetime.timedelta(minutes=5):
                    next_dt = last
                    break
                if agenda[i + 1]["end"] > last:
                    last = agenda[i + 1]["end"]
            else:
                # last element determines end time
                next_dt = last
            if next_dt.date() == now.date():
                txt = "bezet tot {}".format(next_dt.strftime("%H:%M"))
            else:
                txt = "bezet"

        status = {"available": available, "next": next_dt, "status": txt}
        self.logger.debug(
            "Returning {}".format(json.dumps(status, cls=JSONAgendaEncoder))
        )
        return status

    def get_rooms_agendas(self):
        all = dict()
        for room in self.get_rooms().values():
            all[room["number"]] = self.get_agenda_for_day(room["email"])
        return all

    def get_rooms(self):
        if (
            time.time() - self._rooms["updated"] > 24 * 3600
            or self._rooms["data"] is None
        ):
            self.logger.debug(
                "fetching rooms, age=%f" % (time.time() - self._rooms["updated"])
            )
            self._rooms["data"] = self._fetch_rooms()
            self._rooms["updated"] = time.time()

        return self._rooms["data"]

    def _fetch_rooms(self):
        account = self._get_account(self.email)
        all_rooms = dict()
        for roomlist in account.protocol.get_roomlists():
            for room in account.protocol.get_rooms(roomlist.email_address):
                # parse room name for useful info
                # vergaderzaal 4.1 (18p, 75” lcd, conf. telefoon)
                match = re.search("^(\S+) +(\d.\d+) +\((\d+)p", room.name)
                room_type, room_num, room_pers = (
                    match.groups() if match else ("unknown", "0.0", "?")
                )

                if room_num in all_rooms:
                    all_rooms[room_num]["groups"].append(roomlist.email_address)
                else:
                    # parse room number and determine location
                    room_floor, room_floornum = (int(i) for i in room_num.split("."))
                    if room_floor == 3 and room_floornum <= 6:
                        location = "vergadercentrum"
                    elif room_floor == 4 and room_floornum < 10:
                        location = "kantine"
                    elif room_floor == 3:
                        location = "SURF"
                    elif room_floor == 4:
                        location = "SURFnet"
                    elif room_floor == 5:
                        location = "SURFmarket"
                    else:
                        location = "unknown"

                    this_room = {
                        "description": room.name,
                        "email": room.email_address.lower(),
                        "type": room_type,
                        "people": room_pers,
                        "number": room_num,
                        "floor": room_floor,
                        "floor_subnum": room_floornum,
                        "location": location,
                        "groups": [roomlist.email_address],
                    }

                    all_rooms[room_num] = this_room
        return all_rooms


if __name__ == "__main__":
    import configparser

    config = configparser.ConfigParser()
    config.read("webapp.config")
    config = config._sections["config"]

    surfagenda = SurfAgenda(**config)
    # items_today = surfagenda.get_agenda('otheruser@example.org',datetime.date(year=2017,month=4,day=10),datetime.date(year=2017,month=4,day=14))
    print(
        json.dumps(items_today, sort_keys=True, indent=4, cls=JSONAgendaEncoder)
    )  # pprint(items_today)
