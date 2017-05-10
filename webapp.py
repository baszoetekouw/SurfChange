#!/usr/bin/env python3

import flask
import surfagenda
import exchangelib
import json
import configparser
from pprint import pprint


def read_config():
	config = configparser.ConfigParser()
	config.read('webapp.config')
	assert( config.has_section('config') )
	assert( config.has_option('config','username') )
	assert( config.has_option('config','password') )
	assert( config.has_option('config','ad_domain') )
	assert( config.has_option('config','email') )
	assert( config.has_option('config','exchange_endpoint') )
	return config._sections['config']

config = read_config()
exchange = surfagenda.SurfAgenda(**config)
app = flask.Flask(__name__)

def request_wants_json(request):
	best = request.accept_mimetypes \
		.best_match([ 'application/json', 'text/html' ])
	return best == 'application/json' and \
	       request.accept_mimetypes[ best ] > \
	       request.accept_mimetypes[ 'text/html' ]

@app.errorhandler(exchangelib.errors.ErrorNonExistentMailbox)
def handle_bad_request(e):
	if request_wants_json(flask.request):
		data = { "status": 404, "msg": e.__str__ }
		return flask.Response(
			json.dumps(data, sort_keys=True, indent=4),
			mimetype='application/json'
		)
	return flask.render_template('error_no_email.html', error=e), 404

@app.route('/agenda/<email>', defaults={'theDate': 'today'})
@app.route('/agenda/<email>/<theDate>')
def agenda(email, theDate):
	global exchange

	if not '@' in email:
		email = '{}@surfnet.nl'.format(email)

	items, realdate = exchange.get_agenda_for_day(email, theDate)

	if request_wants_json(flask.request):
		return flask.Response(
			json.dumps(items, sort_keys=True, indent=4, cls=surfagenda.JSONAgendaEncoder),
			mimetype='application/json'
		)

	return flask.render_template('agenda.html',email=email,agenda=items,date=realdate)

@app.route('/room/')
def all_rooms():
	global exchange
	rooms = exchange.get_rooms()

	# todo: bezet tot

	if request_wants_json(flask.request):
		return flask.Response(
			json.dumps(rooms,sort_keys=True, indent=4),
			mimetype='application/json'
		)

	kamers = sorted( rooms.values(), key=lambda x: '{floor}.{floor_subnum:02d}'.format(**x) )

	return flask.render_template('kamers.html', kamers=kamers)

@app.route('/room/all/agenda')
def all_room_agenda():
	global exchange
	agendas = exchange.get_rooms_agendas()
	return flask.Response(
		json.dumps(agendas, sort_keys=True, indent=4, cls=surfagenda.JSONAgendaEncoder),
		mimetype='application/json'
	)

if __name__ == '__main__':
	app.run()
