from setuptools import setup

setup(name='surfagenda',
	version='0.1',
	description='Easy access to Exchange calendars',
	url='https://github.com/baszoetekouw/SurfChange',
	author='Bas Zoetekouw',
	author_email='bas.zoetekouw@surfnet.nl',
	license='APL2',
	packages=['surfagenda'],
	install_requires=['exchangelib','ordereddict','flask'],
	python_requires='>=3.4',
	zip_safe=False,
)
