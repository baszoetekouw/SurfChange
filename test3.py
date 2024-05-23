from pprint import pprint

from surfagenda import surfagenda


surf = surfagenda.SurfAgenda('bas.zoetekouw@surf.nl')
surf.authenticate()

agenda = surf.get_agenda_for_day('bas.zoetekouw@surf.nl', "today")

pprint(agenda)