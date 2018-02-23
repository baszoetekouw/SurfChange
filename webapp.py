#!/usr/bin/env python3

import flask
import surfagenda
import exchangelib
import exchangelib.errors
import json
import configparser
import base64
from pprint import pprint


def read_config():
    config = configparser.ConfigParser()
    config.read('webapp.config')
    if not ( config.has_section('config') and config.has_option('config', 'username') and
             config.has_option('config', 'password') and config.has_option('config', 'ad_domain') and
             config.has_option('config', 'email') and config.has_option('config','exchange_endpoint')):
        raise Exception("Invalid config file: missing options")
    return config._sections['config']


config = read_config()
exchange = surfagenda.SurfAgenda(**config)
app = flask.Flask(__name__)


def request_wants_json(request):
    best = request.accept_mimetypes.best_match(['application/json', 'text/html'])
    return best == 'application/json' and request.accept_mimetypes[best] > request.accept_mimetypes['text/html']


@app.context_processor
def utility_processor():
    def b64(str):
        return base64.urlsafe_b64encode(str.encode('utf-8')).decode('utf-8').replace('=', '')

    return dict(base64=b64)


@app.errorhandler(exchangelib.errors.ErrorNonExistentMailbox)
def handle_bad_request(e):
    if request_wants_json(flask.request):
        data = {"status": 404, "msg": e.__str__}
        return flask.Response(json.dumps(data, sort_keys=True, indent=4), mimetype='application/json')
    return flask.render_template('error_no_email.html', error=e), 404


@app.route('/agenda/<email>', defaults={'theDate': 'today'})
@app.route('/agenda/<email>/<theDate>')
def agenda(email, theDate):
    global exchange

    if not '@' in email:
        email = '{}@surfnet.nl'.format(email)

    items, realdate = exchange.get_agenda_for_day(email, theDate)

    if request_wants_json(flask.request):
        return flask.Response(json.dumps(items, sort_keys=True, indent=4, cls=surfagenda.JSONAgendaEncoder),
            mimetype='application/json')

    return flask.render_template('agenda.html', email=email, agenda=items, date=realdate)


@app.route('/kamer/')
@app.route('/room/')
def all_rooms():
    global exchange
    rooms = exchange.get_rooms()

    # todo: bezet tot

    if request_wants_json(flask.request):
        return flask.Response(json.dumps(rooms, sort_keys=True, indent=4), mimetype='application/json')

    kamers = sorted(rooms.values(), key=lambda x: '{floor}.{floor_subnum:02d}'.format(**x))

    return flask.render_template('kamers.html', kamers=kamers)


@app.route('/kamer/alles/agenda')
@app.route('/room/all/agenda')
def all_room_agenda():
    global exchange
    agendas = exchange.get_rooms_agendas()
    return flask.Response(json.dumps(agendas, sort_keys=True, indent=4, cls=surfagenda.JSONAgendaEncoder),
        mimetype='application/json')


@app.route('/issievrij/<email>')
@app.route('/available/<email>')
def availability(email):
    global exchange
    if not '@' in email:
        email = '{}@surfnet.nl'.format(email)

    data = exchange.get_availability(email)

    if request_wants_json(flask.request):
        return flask.Response(json.dumps(data, sort_keys=True, indent=4, cls=surfagenda.JSONAgendaEncoder),
            mimetype='application/json')

    return ""


if __name__ == '__main__':
    app.run()
