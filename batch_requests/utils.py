'''
@author: Rahul Tanwani

@summary: Holds all the utilities functions required to support batch_requests.
'''
import json

from batch_requests.settings import br_settings as _settings
from django.conf import settings
from django.test.client import FakePayload, RequestFactory
from django.utils.encoding import force_bytes


class BatchRequestFactory(RequestFactory):

    '''
        Extend the RequestFactory and update the environment variables for WSGI.
    '''

    def _base_environ(self, **request):
        '''
            Override the default values for the wsgi environment variables.
        '''
        # This is a minimal valid WSGI environ dictionary, plus:
        # - HTTP_COOKIE: for cookie support,
        # - REMOTE_ADDR: often useful, see #8551.
        # See http://www.python.org/dev/peps/pep-3333/#environ-variables

        environ = {
            'HTTP_COOKIE': self.cookies.output(header='', sep='; '),
            'PATH_INFO': '/',
            'REMOTE_ADDR': '127.0.0.1',
            'REQUEST_METHOD': 'GET',
            'SCRIPT_NAME': '',
            'SERVER_NAME': 'localhost',
            'SERVER_PORT': '8000',
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': 'http',
            'wsgi.input': FakePayload(b''),
            'wsgi.errors': self.errors,
            'wsgi.multiprocess': True,
            'wsgi.multithread': True,
            'wsgi.run_once': False,
        }
        environ.update(self.defaults)
        environ.update(request)
        return environ


def pre_process_method_headers(method, headers):
    '''
        Returns the lowered method.
        Capitalize headers, prepend HTTP_ and change - to _.
    '''
    method = method.lower()

    # Standard WSGI supported headers
    _wsgi_headers = ['content_length', 'content_type', 'query_string',
                     'remote_addr', 'remote_host', 'remote_user',
                     'request_method', 'server_name', 'server_port']

    _transformed_headers = {}

    # For every header, replace - to _, prepend http_ if necessary and convert
    # to upper case.
    for header, value in headers.items():

        header = header.replace('-', '_')
        header = 'http_{header}'.format(
            header=header) if header.lower() not in _wsgi_headers else header
        _transformed_headers.update({header.upper(): value})

    return method, _transformed_headers


def headers_to_include_from_request(curr_request):
    '''
        Define headers that needs to be included from the current request.
    '''
    return {
        h: v for h, v in curr_request.META.items() if h in _settings.HEADERS_TO_INCLUDE}


def get_wsgi_request_object(curr_request, method, url, headers, body):
    '''
        Based on the given request parameters, constructs and returns the WSGI request object.
    '''
    x_headers = headers_to_include_from_request(curr_request)
    method, t_headers = pre_process_method_headers(method, headers)

    # Add default content type.
    if 'CONTENT_TYPE' not in t_headers:
        t_headers.update({'CONTENT_TYPE': _settings.DEFAULT_CONTENT_TYPE})

    # Override existing batch requests headers with the new headers passed for this request.
    x_headers.update(t_headers)
    content_type = x_headers.get('CONTENT_TYPE', _settings.DEFAULT_CONTENT_TYPE)

    # Get hold of request factory to construct the request.
    _request_factory = BatchRequestFactory()
    _request_provider = getattr(_request_factory, method)

    data = body
    if data:
        # Check if data is already JSON
        try:
            json.loads(data)
        except (json.decoder.JSONDecodeError, TypeError) as e:
            data = json.dumps(data)

        # https://github.com/django/django/blob/c84b91b7603e488f7171fdff8f08368ef3d6b856/django/test/client.py#L402
        x_headers['CONTENT_LENGTH'] = len(force_bytes(data, settings.DEFAULT_CHARSET))
    else:
        if 'CONTENT_LENGTH' in x_headers:
            x_headers.pop('CONTENT_LENGTH')

    request = _request_provider(
        url,
        data=data,
        secure=_settings.USE_HTTPS,
        content_type=content_type,
        **x_headers
    )

    if hasattr(curr_request, 'user'):
        request.user = curr_request.user

    return request
