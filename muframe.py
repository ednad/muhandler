#!/usr/bin/env python

from __future__ import unicode_literals

import multiprocessing
import gunicorn.app.base, requests
from gunicorn.six import iteritems
from os.path import exists
import simplejson as json
from simplejson.compat import StringIO
import yaml
import datetime as dt
import sys, io, gzip
from werkzeug.wrappers import Response

KEY_SERVICE = "service"
KEY_UFRAME  = "uframe"
KEY_TEST    = "test"
ALIVE = "alive"

CONTENT_TYPE_APPL = [('Content-Type', 'application/json')]
CONTENT_TYPE_JSON = [('Content-Type', 'text/json')]
CONTENT_TYPE_TEXT = [('Content-Type', 'text/html')]
OK_200 = '200 OK'
BAD_REQUEST_400 = '400 Bad Request'
BAD_REQUEST_500 = '500 Internal Server Error'
BAD_REQUEST_502 = '502 Bad Gateway'

# service configuration file and internal variables
c_wsgi_url              = None
c_wsgi_port             = None
c_wsgi_timeout          = None
c_preload_on_start      = None

c_data_root             = None
c_data_folder           = None
c_uframe_url            = None
c_uframe_url_root       = None
c_uframe_timeout_connect= None
c_uframe_timeout_read   = None
c_base_url              = None

options = None          # gunicorn service options
debug   = False         # service debug level messages (always turn off/remove for production)
verbose = True          # service level messages (high level and minimal)

class handler_config():

    wsgi_url              = None
    wsgi_port             = None
    wsgi_timeout          = None
    data_root             = None
    data_folder           = None
    uframe_url            = None
    uframe_url_root       = None
    uframe_timeout_connect= None
    uframe_timeout_read   = None
    base_url              = None
    preload_on_start      = None

    def __init__(self):
        '''
        Open the settings yml, get configuration settings and populate values
        '''
        settings = None
        filename = "muframe.yml"
        root = 'muframe'
        try:
            if exists(filename):
                stream = open(filename)
                settings = yaml.load(stream)
                stream.close()
            else:
                raise IOError('No %s configuration file exists!' % filename)
        except IOError, err:
            print 'IOError: %s' % err.message
            raise Exception(err.message)

        # muframe service, data and uframe settings
        self.wsgi_url         = settings[root]['wsgi_server']['url']
        self.wsgi_port        = settings[root]['wsgi_server']['port']
        self.wsgi_timeout     = settings[root]['wsgi_server']['timeout']
        self.preload_on_start = settings[root]['wsgi_server']['preload']
        self.data_root       = settings[root]['data_root']
        self.data_folder     = settings[root]['data_folder']
        self.uframe_url      = settings[root]['uframe_url']
        self.uframe_url_root = settings[root]['uframe_url_root']
        self.uframe_timeout_connect = settings[root]['uframe_timeout_connect']
        self.uframe_timeout_read    = settings[root]['uframe_timeout_read']
        self.base_url = self.uframe_url + self.uframe_url_root

class manage_store_status():
    '''
    helper for pre-loaded data
    '''
    _file_count = 0
    _filenames = []

    def get_file_count(self):
        self._file_count = len(self.get_filenames())
        return self._file_count
    def get_filenames(self):
        return self._filenames
    def set_saved_files(self, value):
            self._saved_files = value
    def set_filenames(self, value):
            self._filenames = value
    def add_filename(self, value):
        if value:
            if value not in self._filenames:
                self._filenames.append(value)

def print_config_values():
    '''
    debug for use on startup
    '''
    print '\n-------- config values:'
    print '             wsgi_port: %s' % c_wsgi_port                  # service port
    print '              wsgi_url: %s' % c_wsgi_url                   # service host url
    print '          wsgi_timeout: %s' % c_wsgi_timeout               # service worker timeout
    print '      preload_on_start: %s' % c_preload_on_start           # service (on start) preload data
    print '             data_root: %s' % c_data_root                  # location where data folder is located
    print '           data_folder: %s' % c_data_folder                # name of folder where data is stored
    print 'uframe_timeout_connect: %s' % c_uframe_timeout_connect     # connect timeout (should be greater than 3 secs)
    print '   uframe_timeout_read: %s' % c_uframe_timeout_read        # read timeout (adjust to accommodate latency)
    print '            uframe_url: %s' % c_uframe_url                 # uframe url
    print '       uframe_url_root: %s' % c_uframe_url_root            # uframe root
    print '             *base_url: %s' % c_base_url                   # complete url (uframe_url + uframe_root)
    print '----------------------\n'
    return


def format_json(input_str=None):
    """
    Formats input; returns JSON
    """
    io = StringIO()
    json.dump(input_str, io)
    return io.getvalue()

def format_str(input_str=None):
    """
    Formats input; returns str buff. Closes object and discards memory buffer
    """
    output = StringIO()
    output.write(input_str)
    content = output.getvalue()
    output.close()
    return content

def compress(data, compresslevel=9):
    """
    Compress data in one shot, release memory and return the compressed buffer.
    Optional argument is the compression level, in range of 0-9.
    """
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=compresslevel) as f:
        f.write(data)
    content = buf.getvalue()
    buf.close()
    return content

def number_of_workers():
    return (multiprocessing.cpu_count() * 2) + 1

def preload_data():
    '''
    On server initialization, if preload is True, load all uframe data to files.
    Use config settings data_root and data_folder to target storage location.
    '''
    if verbose: print '\nStart data preload ....'

    try:
        response = get_uframe_moorings()
        if response.status_code != 200:
            raise Exception('Failed to get response from uFrame')

        write_store('moorings', response.content)
        mooring_list = response.json()

        platforms = []
        for mooring in mooring_list:
            if 'VALIDATE' in mooring:
                continue # Don't know what this is, but we don't want it
            response = get_uframe_platforms(mooring)
            if response.status_code != 200:
                continue

            write_store(mooring,response.content)
            platform_tmp = [(mooring, p) for p in response.json()]
            platforms.extend(platform_tmp)

        instruments = []
        for platform in platforms:
            response, filename = get_uframe_instruments(*platform)
            if response.status_code != 200:
                continue
            write_store(filename,response.content)
            instrument_tmp = [platform + (i,) for i in response.json()]
            instruments.extend(instrument_tmp)

        stream_types = []
        for instrument in instruments:
            response, filename = get_uframe_stream_types(*instrument)
            if response.status_code != 200:
                continue

            write_store(filename,response.content)
            stream_tmp = [instrument + (s,) for s in response.json()]
            stream_types.extend(stream_tmp)

        streams = []
        for stream_type in stream_types:
            response, filename = get_uframe_streams(*stream_type)
            if response.status_code != 200:
                continue

            write_store(filename,response.content)
            stream_tmp = [stream_type + (s,) for s in response.json()]
            streams.extend(stream_tmp)

        for stream in streams:
            response, filename = get_uframe_stream_contents(*stream)
            if response.status_code != 200:
                continue

            write_store(filename,response.content)

        # [no data] get_uframe_stream(mooring, platform, instrument, stream)
        for stream in streams:
            tmp = (stream[0], stream[1], stream[2], stream[4])
            response, filename = get_uframe_stream(*tmp)
            if response.status_code != 200:
                continue

            write_store(filename,response.content)

        # [no data] get_uframe_stream_metadata(mooring, platform, instrument, stream)
        for stream in streams:
            tmp = (stream[0], stream[1], stream[2], stream[4])
            response, filename = get_uframe_stream_metadata(*tmp)
            if response.status_code != 200:
                continue

            write_store(filename,response.content)

        if verbose: print ' - Number of preloaded files: %s ' % store_status.get_file_count()

    except Exception, err:
        if debug: print 'error: %s' % err.message
        raise Exception('%s' % err.message)

    if verbose: print 'Completed data preload ....\n'

    return

def get_uframe_moorings():
    '''
    Lists all the streams
    '''
    try:
        url = c_base_url
        if debug: print url
        response = requests.get(url)
        return response
    except:
        raise Exception('uframe connection cannot be made.')

def get_uframe_platforms(mooring):
    '''
    Lists all the streams
    '''
    try:
        url = c_base_url + '/' + mooring
        if debug: print url
        response = requests.get(url)
        return response
    except:
        raise Exception('uframe connection cannot be made.')

def get_uframe_instruments(mooring, platform):
    '''
    Lists all the streams
    '''
    try:
        filename = '_'.join([mooring, platform])
        url = c_base_url + '/' + mooring + '/' + platform
        if debug: print url
        response = requests.get(url)
        return response, filename
    except:
        raise Exception('uframe connection cannot be made.')

def get_uframe_stream_types(mooring, platform, instrument):
    '''
    Lists all the streams
    '''
    try:
        filename = '_'.join([mooring, platform, instrument])
        url = '/'.join([c_base_url, mooring, platform, instrument])
        if debug: print url
        response = requests.get(url)
        return response, filename
    except:
        raise Exception('uframe connection cannot be made.')

def get_uframe_streams(mooring, platform, instrument, stream_type):
    '''
    Lists all the streams
    '''
    try:
        filename = '_'.join([mooring, platform, instrument, stream_type])
        url = '/'.join([c_base_url, mooring, platform, instrument, stream_type])
        if debug: print url
        response = requests.get(url)
        return response, filename
    except:
        raise Exception('uframe connection cannot be made.')

def get_uframe_stream(mooring, platform, instrument, stream):
    '''
    Lists the reference designators for the streams
    '''
    try:
        filename = '_'.join([mooring, platform, instrument, stream])
        url = "/".join([c_base_url, mooring, platform, instrument, stream])
        response = requests.get(url)
        if debug: print '*', url
        return response, filename
    except:
        raise Exception('uframe connection cannot be made.')

def get_uframe_stream_metadata(mooring, platform, instrument, stream):
    '''
    Returns the uFrame metadata response for a given stream
    '''
    try:
        filename = '_'.join([mooring, platform, instrument, stream, 'metadata'])
        url = "/".join([c_base_url,mooring, platform, instrument, stream, 'metadata'])
        if debug: print '*', url
        response = requests.get(url)
        return response, filename
    except:
        raise Exception('uframe connection cannot be made.')

def get_uframe_stream_contents(mooring, platform, instrument, stream_type, stream):
    '''
    Gets the stream contents
    '''
    try:
        filename = '_'.join([mooring, platform, instrument, stream_type, stream])
        url = "/".join([c_base_url, mooring, platform, instrument, stream_type, stream])
        if debug: print url
        response =  requests.get(url)
        if response.status_code != 200:
            pass
        return response, filename
    except:
        raise Exception('uframe connection cannot be made.')

def write_store(filename, data):
    '''
    open filename, write data and close file;
    '''
    try:
        tmp = "/".join([c_data_root,c_data_folder, filename])
        f = open(tmp, 'wb')
        f.write(data)
        f.close()
        store_status.add_filename(filename)
    except Exception, err:
        if debug: print 'error writing data to store: err: %s' % err.message
        raise Exception('%s' % err.message)

    return None

def read_store(filename):
    '''
    open filename, read data, close file and return data
    '''
    data = None
    try:
        tmp = "/".join([c_data_root,c_data_folder, filename])
        f = open(tmp, 'rb')
        data = f.read()
        f.close()
    except Exception, err:
        if debug: print 'error reading data from store: err: %s' % err.message
        raise Exception('%s' % err.message)
    return data

def handler_app(environ, start_response):
    request = environ['PATH_INFO']
    request = request[1:]
    req = request.split("&")
    param_dict = {}
    if len(req) > 1:
        for param in req:
            params = param.split("=")
            param_dict[params[0]] = params[1]
    else:
        if "=" in request:
            params = request.split("=")
            param_dict[params[0]] = params[1]
        else:
            # echo request in response
            output = ['Unknown key: ' + request ]
            start_response(OK_200, CONTENT_TYPE_TEXT)
            return format_json(output)

    # TODO Prepare headers once on initialization, not every time
    # Prepare basic headers for all responses
    dict_zip_header = {'access-control-expose-headers': '[]', 'content-encoding': 'gzip', 'access-control-allow-credentials': 'false', 'access-control-allow-origin': '*', 'content-type': 'application/json'}
    zip_header = []
    for k,v in dict_zip_header.iteritems():
        zip_header.append((k,v))

    dict_regular_header = {'access-control-expose-headers': '[]', 'transfer-encoding': 'chunked', 'server': 'Jetty(7.6.14.v20131031)', 'access-control-allow-credentials': 'false', 'date': 'Thu, 26 Feb 2015 20:47:20 GMT', 'access-control-allow-origin': '*', 'content-type': 'application/json'}
    regular_header = []
    for k,v in dict_regular_header.iteritems():
        regular_header.append((k,v))

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # KEY_SERVICE Section (alive, stream_name, stream_name/reference_designator)
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    if KEY_SERVICE in param_dict:
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # 0. process service=alive (availability check)
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        if param_dict[KEY_SERVICE] == ALIVE:
            print '\n\n- process service=alive \n'
            input_str={'Service Response': 'Alive'}
            start_response(OK_200, CONTENT_TYPE_JSON)
            return format_json(input_str)

        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # 1. process service=c_uframe_url_root (e.g. fetch list of streams)
        # Sample url:  http://localhost:7090/uframe=/sensor/inv
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        elif param_dict[KEY_SERVICE] == c_uframe_url_root:
            status_code = 500
            response_text = None
            try:
                url = c_base_url
                if verbose: print 'process: service=%s' % url
                try:
                    start = dt.datetime.now()
                    filename = 'moorings'
                    check_list = store_status.get_filenames()
                    if filename not in check_list:
                        raise Exception('no store available for this request')
                    store_path =  '/'.join([c_data_root, c_data_folder,  filename])
                    if exists(store_path):
                        status_code = 200
                        response_text = read_store(filename)
                        end = dt.datetime.now()
                        if debug: print '(service=) time: %s' % str(end-start)
                        if not response_text:
                            status_code = 400
                            raise Exception('empty store for: %s' % store_path)
                    else:
                        status_code = 400
                        raise Exception('unable to locate: %s' % store_path)

                except Exception, err:
                    if debug: print 'Error: %s' % err.message
                    input_str={'Error': '%s' % err.message}
                    header = regular_header
                    r = Response(format_json(input_str))
                    r.status_code = status_code
                    r.headers = header
                    return r(environ, start_response)

                # Create a Response object
                output = response_text
                header = regular_header
                r = Response(output)
                r.status_code = status_code
                r.headers = header
                return r(environ, start_response)

            except Exception, err:
                input_str={'Error' : '%s' % err.message}
                if status_code == 200:
                    status_code = 500
                    input_str={'Error': 'error processing uframe response: %s' % err.message}
                if debug: print 'Error: %s' % err.message
                r = Response(format_json(input_str))
                r.status_code = status_code
                r.headers = regular_header
                return r(environ, start_response)

        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # 2. process service=valid_uframe_request
        # Test url: http://localhost:7090/service=/sensor/inv/CP02PMCO/SBS01/01-MOPAK0000/telemetered/mopak_o_dcl_accel
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        elif c_uframe_url_root in param_dict[KEY_SERVICE]:
            status_code = 500
            try:
                if verbose: print 'process: service=%s' % param_dict[KEY_SERVICE]
                start = dt.datetime.now()
                params = param_dict[KEY_SERVICE]
                check_list = store_status.get_filenames()
                req = params.replace((c_uframe_url_root+'/'), '') # remove '/sensor/inv/' from params
                compression_count = 9
                if '/' in req:
                    compression_count = req.count('/')
                    filename = req.replace('/','_')
                else:
                    filename = req
                try:
                    if filename in check_list:
                        store_path =  '/'.join([c_data_root, c_data_folder,  filename])
                        if exists(store_path):
                            response_text = read_store(filename)
                            status_code = 200
                        else:
                            status_code = 400
                            raise Exception('unable to locate: %s' % store_path)
                        end = dt.datetime.now()
                        if debug: print '(service=) time: %s' % str(end-start)
                    else:
                        status_code = 400
                        raise Exception('do not have this saved as a store: %s' % filename)

                except Exception, err:
                    if debug: print 'Error: %s' % err.message
                    input_str={'Error': '%s' % err.message}
                    header = regular_header
                    r = Response(format_json(input_str))
                    r.status_code = status_code
                    r.headers = header
                    return r(environ, start_response)

                # Create a Response object using compressed uframe response.text and local header with gzip
                if compression_count < 4:
                    output = response_text
                    header = regular_header
                else:
                    output = compress(response_text, 9)
                    header = zip_header
                r = Response(output)
                r.status_code = status_code
                r.headers = header
                return r(environ, start_response)

            except Exception, err:
                input_str={'Error' : '%s' % err.message}
                if status_code == 200:
                    status_code = 500
                    input_str={'Error': 'error processing uframe response: %s' % err.message}
                if debug: print 'Error: %s' % err.message
                r = Response(format_json(input_str))
                r.status_code = status_code
                r.headers = regular_header
                return r(environ, start_response)

        # Specified service parameter is not valid (e.g. service=some_invalid_request)
        # returns json
        else:
            input_str={'Error': 'Unknown service parameter in request: \'%s\' ' % request }
            if debug: print 'Error: Unknown service parameter in request: \'%s\' ' % request
            r = Response(format_json(input_str))
            r.status_code = 400
            r.headers = regular_header
            return r(environ, start_response)

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # KEY_UFRAME Section (alive, uframe request)
    #- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    elif KEY_UFRAME in param_dict:
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # 0. verify service is available
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        if param_dict[KEY_UFRAME] == ALIVE:
            if verbose: print '\n\n- process uframe=alive \n'
            input_str={'Service Response': 'Alive'}
            start_response(OK_200, CONTENT_TYPE_JSON)
            return format_json(input_str)
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # 1. process c_uframe_url_root (e.g. fetch list of moorings)
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        elif param_dict[KEY_UFRAME] == c_uframe_url_root:
            status_code = 500
            try:
                url = c_base_url
                if verbose: print 'process: uframe=%s' % c_uframe_url_root
                try:
                    start = dt.datetime.now()
                    response = requests.get(url,timeout=(c_uframe_timeout_connect, c_uframe_timeout_read))
                    end = dt.datetime.now()
                    if debug: print '(uframe=) time: %s' % str(end-start)
                    if response:
                        status_code = response.status_code
                        if response.status_code != 200:
                            raise Exception('status code %s for url: %s' % (str(response.status_code), url))
                    else:
                        status_code = 500
                        raise Exception('Failed to receive uframe response; verify config values for uframe')

                except Exception, err:
                    if debug: print 'Error: %s' % err.message
                    input_str={'Error': '%s' % err.message}
                    header = regular_header
                    r = Response(format_json(input_str))
                    r.status_code = status_code
                    r.headers = header
                    return r(environ, start_response)

                # Create a Response object using compressed uframe response.text and local header with gzip
                output = compress(response.text, 9)
                header = zip_header
                r = Response(output)
                r.status_code = status_code
                r.headers = header
                return r(environ, start_response)

            except Exception, err:
                input_str={'Error' : '%s' % err.message}
                if status_code == 200:
                    status_code = 500
                    input_str={'Error': 'error processing uframe response: %s' % err.message}

                if debug: print 'Error: %s' % err.message
                r = Response(format_json(input_str))
                r.status_code = status_code
                r.headers = regular_header
                return r(environ, start_response)

        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # 2. process uframe==valid_uframe_request
        # Example: http://localhost:7090/service=/sensor/inv/CP02PMCO/SBS01/01-MOPAK0000/telemetered/mopak_o_dcl_accel
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        elif c_uframe_url_root in param_dict[KEY_UFRAME]:
            status_code = 500
            try:
                if verbose: print 'process: uframe=%s' % param_dict[KEY_UFRAME]
                params = param_dict[KEY_UFRAME]
                url = c_uframe_url + params
                try:
                    start = dt.datetime.now()
                    response = requests.get(url,timeout=(c_uframe_timeout_connect, c_uframe_timeout_read))
                    end = dt.datetime.now()
                    if debug: print '(uframe=) time: %s' % str(end-start)
                    if response:
                        status_code = response.status_code
                        if response.status_code != 200:
                            raise Exception('status code %s for url: %s' % (str(response.status_code), url))
                    else:
                        status_code = 500
                        raise Exception('Failed to receive uframe response; verify config values for uframe')

                except Exception, err:
                    if debug: print 'Error: %s' % err.message
                    input_str={'Error': '%s' % err.message}
                    header = regular_header
                    r = Response(format_json(input_str))
                    r.status_code = status_code
                    r.headers = header
                    return r(environ, start_response)

                # Create a Response object using compressed uframe response.text and local header with gzip
                output = compress(response.text, 9)
                header = zip_header
                r = Response(output)
                r.status_code = status_code
                r.headers = header
                return r(environ, start_response)

            except Exception, err:
                input_str={'Error' : '%s' % err.message}
                if status_code == 200:
                    status_code = 500
                    input_str={'Error': 'error processing uframe response: %s' % err.message}

                if debug: print 'Error: %s' % err.message
                r = Response(format_json(input_str))
                r.status_code = status_code
                r.headers = regular_header
                return r(environ, start_response)

        # Specified uframe parameter is not valid (e.g. uframe=some_invalid_request)
        # returns json
        else:
            input_str={'Error': 'Unknown uframe parameter in request: \'%s\' ' % request }
            if debug: print 'Error: Unknown uframe parameter in request: \'%s\' ' % request
            r = Response(format_json(input_str))
            r.status_code = 400
            r.headers = regular_header
            return r(environ, start_response)

    # key not known (e.g. not 'service=' or 'uframe=')
    else:
        input_str='{ Error: unknown key provided in request: %s } ' % request
        print 'Error: Error: unknown key provided in request: \'%s\' ' % request
        start_response(OK_200, CONTENT_TYPE_TEXT)
        return format_json(input_str)


class StandaloneApplication(gunicorn.app.base.BaseApplication):
    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super(StandaloneApplication, self).__init__()

    def load_config(self):
        config = dict([(key, value) for key, value in iteritems(self.options)
                       if key in self.cfg.settings and value is not None])
        for key, value in iteritems(config):
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application

if __name__ == '__main__':
    try:
        '''
        read configuration yml, set service variables (c_*) and sanity check;
        apply to service options dictionary for service initialization.
        '''
        store_status = manage_store_status()
        util = handler_config()
        c_wsgi_port       = util.wsgi_port
        c_wsgi_url        = util.wsgi_url
        c_wsgi_timeout    = 30                      # set default, override if config value acceptable
        _wsgi_timeout     = util.wsgi_timeout       # worker timeout config value
        c_data_root       = util.data_root
        c_data_folder     = util.data_folder
        c_uframe_url      = util.uframe_url
        c_uframe_url_root = util.uframe_url_root
        c_uframe_timeout_connect = util.uframe_timeout_connect
        c_uframe_timeout_read    = util.uframe_timeout_read
        c_base_url        = c_uframe_url + c_uframe_url_root
        c_preload_on_start= util.preload_on_start

        # set default worker timeout (seconds); verify worker timeout value in config is int and GE 30;
        if _wsgi_timeout:
            if type(_wsgi_timeout) == type(1):
                if _wsgi_timeout < 30:
                    c_wsgi_timeout = 30
                else:
                    c_wsgi_timeout = _wsgi_timeout
            else:
                raise Exception('config variable \'timeout\' must be an integer')

        if type(c_uframe_timeout_connect) != type(1):
            raise Exception('config variable \'uframe_timeout_connect\' must be an integer')
        if type(c_uframe_timeout_read) != type(1):
            raise Exception('config variable \'uframe_timeout_read\' must be an integer')

        # Verify service_url and port are not None
        if not c_wsgi_url or not c_wsgi_port:
            raise Exception('Service host url and port must have values defined in configuration yml')

        # Verify c_data_root and c_data_folder are provided and exist
        if not exists(c_data_root):
            raise Exception('data_root not configured properly, unable to access')
        if not exists(c_data_root + '/' + c_data_folder):
            raise Exception('data_folder not configured properly, unable to access')

        # set options for service instance; note service name 'muframe'
        options = {
                'bind': '%s:%s' % (str(c_wsgi_url), str(c_wsgi_port)),
                'workers': number_of_workers(),
                'timeout': c_wsgi_timeout,
                'proc_name': 'muframe'
            }
        if debug == True: print_config_values()

        # preload data before starting server (in configuration file)
        # Note if True, this delays availability of server until preload completes
        if c_preload_on_start:
            preload_data()

        # Start server
        StandaloneApplication(handler_app, options).run()

    except Exception, err:
        sys.exit('\nError: %s\n' % err.message)
