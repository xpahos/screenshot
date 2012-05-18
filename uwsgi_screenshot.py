import os
import sys
import mmap
from cgi import parse_qs, escape
from hashlib import md5
import redis 
import pickle
import datetime

SIZE_LIST = ['120', '240', '400']
STATIC_PATH = '/srv/www/screenshot/static/'
SERVER_LOG = '/var/log/screenshot/server.log'

connection = redis.Redis("localhost")

class NotFound(Exception):
    pass

def status_info():
    ll = connection.llen('low_priority')
    hl = connection.llen('high_priority')

    _date = datetime.datetime.fromtimestamp(0)
    avg_5_submitted = 0
    avg_5_completed = 0
    avg_10_submitted = 0
    avg_10_completed = 0 
    avg_15_submitted = 0 
    avg_15_completed = 0 

    try:
        _date = datetime.datetime.fromtimestamp(float(connection.hget('avg', '5_date')))
        avg_5_submitted = connection.hget('stats', 'avg5_submitted')
        avg_5_completed = connection.hget('stats', 'avg5_completed')
        avg_10_submitted = connection.hget('stats', 'avg10_submitted')
        avg_10_completed = connection.hget('stats', 'avg10_completed')
        avg_15_submitted = connection.hget('stats', 'avg15_submitted')
        avg_15_completed = connection.hget('stats', 'avg15_completed')
    except:
        pass
    output = """
<html>
    <head>
        <title>Screenshot status</title>
        <style type="text/css">
            ul {{ padding: 5px; }}
            li {{ list-style-type: none; padding: 2px; }}

            .highlight {{ background-color: #EEE; }}
        </style>
        <META http-equiv="refresh" content="300" />
    <head>
    <body>
        <h3>Queue status:</h3>
        <strong>last update:</strong> {la}<br />
	<strong>high priority:</strong> {hl}<br />
	<strong>low priority:</strong> {ll}<br />
        <br />
        <table style="text-align: center">
            <tr><td>avg</td><td><b>5</b></td><td><b>10</b></td><td><b>15</b></td></tr>
            <tr><td><b>submitted</b></td><td>{avg_5_submitted}</td><td>{avg_10_submitted}</td><td>{avg_15_submitted}</td></tr>
            <tr><td><b>completed</b></td><td>{avg_5_completed}</td><td>{avg_10_completed}</td><td>{avg_15_completed}</td></tr>
	</table>
    </body>
</html>""".format(
        hl = hl, 
        ll = ll,
        la = _date.strftime('%H:%M %m/%d/%Y'),
        avg_5_submitted = avg_5_submitted,
        avg_10_submitted = avg_10_submitted,
        avg_15_submitted = avg_15_submitted,
        avg_5_completed = avg_5_completed,
        avg_10_completed = avg_10_completed,
        avg_15_completed = avg_15_completed)
    
    return output

def check_path_info(environ):
    if environ['PATH_INFO'] == '/get.php' or environ['PATH_INFO'] == '/stats.php':
        return True
    else:
        return False

def application(environ, start_response):
    try:
	if not check_path_info(environ):
            raise NotFound
        
        if environ['PATH_INFO'] == '/stats.php':
            output = status_info()
            response_headers = [('Content-type', 'text/html'),
                        ('Content-Length', str(len(output)))]
            start_response('200 OK', response_headers)
            return [output]

        query = parse_qs(environ['QUERY_STRING'])

	try:
            url = query.get('url', [''])[0]
            size = query.get('s', [120])[0]
            v = query.get('v', [0])[0]
        except IndexError:
            raise NotFound

        if not size in SIZE_LIST:
            size = 120 

        try:
            if int(v) == 1:
                priority = True
            else:
                priority = False
        except ValueError:
            raise NotFound

	md5_url = md5(url).hexdigest()
        file = '{0}{1}/{2}/{3}/{4}/{5}.jpg'.format(STATIC_PATH, size, md5_url[0], md5_url[1], md5_url[2], md5_url)
        file_path = '{0}{1}/{2}/{3}/{4}/'.format(STATIC_PATH, size, md5_url[0], md5_url[1], md5_url[2])
        try:
            file = open(file)
        except IOError:
            if priority:
                connection.rpush('high_priority', pickle.dumps({'url' : url, 'size' : size, 'path' : file_path, 'md5_url' : md5_url, 'file' : file }))
            else:
                connection.rpush('low_priority', pickle.dumps({'url' : url, 'size' : size, 'path' : file_path, 'md5_url' : md5_url, 'file' : file }))
            connection.hincrby('stats', 'submitted', 1)

            file = open('{0}{1}.jpg'.format(STATIC_PATH, size))
        output = file.read() 

        response_headers = [('Content-type', 'image/jpg'),
                        ('Content-Length', str(len(output)))]
        start_response('200 OK', response_headers)

    except NotFound:
        output = ''
        response_headers = [('Content-type', 'image/jpg'),
                        ('Content-Length', str(len(output)))]
        start_response('404 Not Found', response_headers)

    return [output]

