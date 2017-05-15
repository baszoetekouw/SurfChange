#!/usr/bin/python3

import exchangelib

from pprint import pprint
import datetime
import dateutil.parser
import time
import pytz
import json
import re


# from http://stackoverflow.com/questions/9868653/find-first-sequence-item-that-matches-a-criterium
def findfirst(items, pred):
	return next(
		( i for i in enumerate(items) if pred(i[1]) ),
		(None,None)
	)


class JSONAgendaEncoder(json.JSONEncoder):
	def default(self, o):
		if isinstance(o, datetime.datetime):
			return o.isoformat()
		elif isinstance(o, datetime.date):
			return o.strftime("%Y-%m-%d")
		else:
			return json.JSONEncoder.default(self, o)


class SurfAgenda:
	def __init__(self, email, username, password, ad_domain,
			tz='Europe/Amsterdam', exchange_endpoint=None,
			exchange_authtype='NTLM'):
		self.username = username
		self.domain   = ad_domain
		self.login    = '%s\%s' % (self.domain,self.username)
		self.email    = email
		self.password = password
		self.credentials = exchangelib.ServiceAccount(self.login,self.password,max_wait=5)
		self.tz = pytz.timezone(tz)

		self.default_endpoint = exchange_endpoint
		self.default_authtype = exchange_authtype

		# use autodiscovery if no endpoint was specified
		if self.default_endpoint:
			self._connect(False)
		else:
			self._connect(True)

		self._rooms = { "updated": 0 ,"data": None }

	def _connect(self, force_autodiscovery=False):
		if force_autodiscovery:
			(endpoint,auth_type) = self._do_autodiscovery()
		else:
			endpoint  = self.default_endpoint
			auth_type = self.default_authtype

		self.config = exchangelib.Configuration(
			service_endpoint=endpoint,
			auth_type=auth_type,
			credentials = self.credentials
		)


	def _do_autodiscovery(self,force=False):
		account = exchangelib.Account(
			primary_smtp_address=self.email,
			credentials=self.credentials,
			autodiscover=True,
			access_type=exchangelib.DELEGATE
		)
		assert(account is not None)

		return account.protocol.service_endpoint, account.protocol.auth_type

	def _get_account(self,email):
		assert(self.config)
		account = exchangelib.Account(
			primary_smtp_address=email,
			config=self.config,
			autodiscover=False,
			access_type=exchangelib.DELEGATE
		)
		return account

	def _parse_date(self, date):
		if isinstance(date, datetime.date):
			return date
		if isinstance(date,datetime.datetime):
			return date.date()

		if date=='today' or date=='vandaag':
			return datetime.date.today()
		if date=='tomorrow' or date=='morgen':
			return datetime.date.today()+datetime.timedelta(days=1)
		if date=='dayaftertomorrow' or date=='dat' or date=='overmorgen':
			return datetime.date.today()+datetime.timedelta(days=2)
		if date[0]=='+':
			numdays = int( date[1:] )
			return datetime.date.today()+datetime.timedelta(days=numdays)

		return dateutil.parser.parse(date, dayfirst=True, yearfirst=False)

	def get_agenda(self, email, dt_start, dt_stop):
		assert(self.config)
		account = self._get_account(email)

		assert( isinstance(dt_start,datetime.datetime) and isinstance(dt_stop,datetime.datetime) )
		if (dt_stop < dt_start):
			return list()

		agenda_items = account.calendar.view(
			exchangelib.EWSDateTime.from_datetime(dt_start),
			exchangelib.EWSDateTime.from_datetime(dt_stop)
		)
		agenda_items = sorted(agenda_items, key=lambda a: a.start)

		meetings = list()
		for item in agenda_items:
			#print("===========================")
			#print(item)

			is_private = (item.sensitivity.lower() == 'private')

			attendees = list()
			if item.required_attendees and not is_private:
				attendees.append( [ (p.mailbox.name,p.mailbox.email_address) for p in item.required_attendees ] )
			if item.optional_attendees and not is_private:
				attendees.append( [ (p.mailbox.name,p.mailbox.email_address) for p in item.optional_attendees ] )

			organizer = ('','')
			if item.organizer and not is_private:
				organizer = (item.organizer.name, item.organizer.email_address)

			meeting = dict({
				'start':      item.start.astimezone(self.tz),
				'end':        item.end.astimezone(self.tz),
				'time_start': item.start.astimezone(self.tz).strftime('%H:%M'),
				'time_end':   item.end.astimezone(self.tz).strftime('%H:%M'),
				'date_start': item.start.astimezone(self.tz).strftime('%Y-%m-%d'),
				'date_end':   item.end.astimezone(self.tz).strftime('%Y-%m-%d'),
				'all_day':    item.is_all_day,
				'organizer':  organizer,
				'subject':    item.subject  if not is_private else "Private appointment",
				'location':   item.location if not is_private else "Undisclosed",
				'attendees':  attendees,
			})
			meetings.append(meeting)

		# this probably is already sorted, but let's just make sure
		meetings = sorted(meetings, key=lambda a: a['start'])

		return meetings

	def get_agenda_for_days(self, email, date_start, date_stop):
		assert (isinstance(date_start, datetime.date) and isinstance(date_stop, datetime.date))

		dt_start = datetime.datetime.combine(date_start, datetime.time(hour=0, minute=0, tzinfo=self.tz))
		dt_stop = datetime.datetime.combine(date_stop, datetime.time(hour=23, minute=59, second=59, tzinfo=self.tz))

		return self.get_agenda(email,dt_start,dt_stop)

	def get_agenda_for_day(self, email, date=datetime.date.today()):
		realdate = self._parse_date(date)
		assert( isinstance(realdate,datetime.date) )
		return self.get_agenda_for_days(email, realdate, realdate), realdate

	def get_availability(self, email, date=datetime.date.today()):
		agenda, realdate = self.get_agenda_for_day(email, date)
		now = datetime.datetime.now(tz=self.tz)
		now = now.replace(hour=14,minute=15)

		# walk through list to find current/next meeting
		index_next, entry_next = findfirst(agenda, lambda a: a['end']>now)

		# three possibilities now:
		# (1) no further meetings today (nothing found, None returned)
		# (2) room is currently free (so next meeting hasn't started)
		# (3) room is currently occupied (next meeting has started)
		if index_next is None:
			available = True
			next_dt = None
			txt = "vrij"
		elif entry_next['start']>=now:
			available = True
			next_dt = entry_next['start']
			if next_dt.date()==now.date():
				txt = "vrij tot {}".format(next_dt.strftime('%H:%M'))
			else:
				txt = "vrij"
		else:
			available = False
			# find next available slot by checking for a gap between meeting of at least 5 minutes
			# keep track of latest endtime of all relevant meetings
			last = entry_next['end']
			for i, a in enumerate( agenda[index_next:-2], index_next ):
				if agenda[i+1]['start'] - last > datetime.timedelta(minutes=5):
					next_dt = last
					break
				if agenda[i+1]['end']>last:
					last = agenda[i+1]['end']
			else:
				# last element determines end time
				next_dt = last
			if next_dt.date()==now.date():
				txt = "bezet tot {}".format(next_dt.strftime('%H:%M'))
			else:
				txt = "bezet"

		return available, next_dt, txt

	def get_rooms_agendas(self):
		all = dict()
		for room in self.get_rooms().values():
			all[room['number']] = self.get_agenda_for_day(room['email'])
		return all

	def get_rooms(self):
		if time.time()-self._rooms['updated']>24*3600 or self._rooms['data'] is None:
			print("fetching rooms, age=%f" % (time.time()-self._rooms['updated']))
			self._rooms['data']    = self._fetch_rooms()
			self._rooms['updated'] = time.time()

		return self._rooms['data']

	def _fetch_rooms(self):
		account = self._get_account(self.email)
		all_rooms = dict()
		for roomlist in account.protocol.get_roomlists():
			for room in account.protocol.get_rooms(roomlist.email_address):
				# parse room name for useful info
				# vergaderzaal 4.1 (18p, 75” lcd, conf. telefoon)
				match = re.search('^(\S+) +(\d.\d+) +\((\d+)p',room.name)
				room_type, room_num, room_pers = match.groups()  if  match  else  ("unknown","0.0","?")

				if room_num in all_rooms:
					all_rooms[room_num]["groups"].append(roomlist.email_address)
				else:
					# parse room number and determine location
					room_floor, room_floornum = ( int(i) for i in room_num.split('.') )
					if room_floor==3 and room_floornum <=6:
						location = "vergadercentrum"
					elif room_floor==4 and room_floornum<10:
						location = "kantine"
					elif room_floor==3:
						location = "SURF"
					elif room_floor==4:
						location = "SURFnet"
					elif room_floor==5:
						location = "SURFmarket"
					else:
						location = "unknown"

					this_room = {
						"description" : room.name,
						"email"       : room.email_address.lower(),
						"type"        : room_type,
						"people"      : room_pers,
						"number"      : room_num,
						"floor"       : room_floor,
						"floor_subnum": room_floornum,
						"location"    : location,
						"groups"      : [roomlist.email_address],
					}

					all_rooms[room_num] = this_room
		return(all_rooms)


if __name__ == "__main__":
	surfagenda = SurfAgenda(username='user', password='s3cr1t')
	items_today = surfagenda.get_agenda_for_day('user@example.org')
	#items_today = surfagenda.get_agenda('otheruser@example.org',datetime.date(year=2017,month=4,day=10),datetime.date(year=2017,month=4,day=14))
	print(json.dumps(items_today, sort_keys=True, indent=4, cls=JSONAgendaEncoder))
	#pprint(items_today)
