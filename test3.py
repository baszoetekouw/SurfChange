from pprint import pprint

from surfagenda import surfagenda


surf = surfagenda.SurfAgenda()
surf.authenticate()

agenda = surf.get_agenda_for_day(date="today")
pprint(agenda)

agenda = surf.get_agenda_for_day(date="today", email='floris.fokkinga@surf.nl')
pprint(agenda)