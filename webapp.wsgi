# vim:ft=python

activate_this = '/home/bas/SurfChange/code/activate_this.py'
with open(activate_this) as file_:
    exec(file_.read(), dict(__file__=activate_this))

from webapp import app as application

