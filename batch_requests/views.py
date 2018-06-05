'''
@author: Rahul Tanwani

@summary: A module to perform batch request processing.
'''

import json
from datetime import datetime

from batch_requests.exceptions import BadBatchRequest
from batch_requests.jsonapi import JsonApiRewriter
from batch_requests.settings import br_settings as _settings
from batch_requests.utils import get_wsgi_request_object

from django.db import transaction
from django.http import Http404
from django.http.response import HttpResponse, HttpResponseBadRequest, HttpResponseServerError
from django.urls import resolve
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


def withDebugHeaders(view_handler):
    '''
        Decorator which wraps functions processing wsgi_requests and returning a dictionary,
        to which it adds a header item containing information about time taken and request url.
    '''
    def inner(wsgi_request):

        # We now always get a tuple for the WSGI request object, the
        # first element is the request, the second is the onward
        # variables.
        # TODO: I think we can conver the onward variables implementation
        #  to a different rewriter.
        if isinstance(wsgi_request, tuple):
            wsgi_request, onward_variables = wsgi_request

        service_start_time = datetime.now()
        result = view_handler(wsgi_request)

        # Check if we need to send across the duration header.
        if not _settings.ADD_DURATION_HEADER:
            return result

        time_taken = (datetime.now() - service_start_time).microseconds / 1000

        result.setdefault('headers', {})
        result['headers'].update({
            'request_url': wsgi_request.path_info,
            _settings.DURATION_HEADER_NAME: time_taken,
        })
        return result
    return inner


@withDebugHeaders
def get_response(wsgi_request):
    '''
        Given a WSGI request, makes a call to a corresponding view
        function and returns the response.
    '''
    # Get the view / handler for this request
    try:
        view, args, kwargs = resolve(wsgi_request.path_info)
    except Http404 as error:
        return {'status_code': 404, 'reason_phrase': 'Page not found'}

    # Let the view do his task.
    kwargs.update({'request': wsgi_request})
    try:
        response = view(*args, **kwargs)
    except Exception as exc:
        response = HttpResponseServerError(content=str(exc))

    # Convert HTTP response into simple dict type.
    result = {
        'status_code': response.status_code,
        'reason_phrase': response.reason_phrase,
        'headers': dict(response._headers.values()),
    }

    # Make sure that the response has been rendered
    if hasattr(response, 'render') and callable(response.render):
        response.render()

    content = response.content
    if isinstance(content, bytes):
        content = content.decode('utf-8')

    try:
        content = json.loads(content)
    except json.JSONDecodeError:
        pass

    result['body'] = content
    return result


def construct_wsgi_from_data(request, data, replace_params={}, rewriter=None):
    '''
    Given the data in the format of url, method, body and headers, construct a new
    WSGIRequest object.
    '''
    valid_http_methods = [
        'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'connect', 'trace'
    ]

    if rewriter:
        rewriter.rewrite_request(data)

    url = data.get('url', None)
    method = data.get('method', None)

    if url is None or method is None:
        raise BadBatchRequest('Request definition should have url, method defined.')

    if method.lower() not in valid_http_methods:
        raise BadBatchRequest('Invalid request method.')

    body = None
    if method.lower() not in ['get', 'options']:
        body = data.get('body', '')
        for name, value in replace_params.items():
            placeholder = '"{{' + name + '}}"'
            body = json.loads(json.dumps(body).replace(placeholder, value))

    headers = data.get('headers', {})
    onward_variables = data.get('onward_data', {})
    wsgi_request = get_wsgi_request_object(request, method, url, headers, body)
    return (wsgi_request, onward_variables)


def get_requests_data(request):
    '''
        For the given batch request, extract the individual requests and create
        WSGIRequest object for each.
    '''
    requests = json.loads(request.body).get('batch', [])

    if type(requests) not in (list, tuple):
        raise BadBatchRequest('The body of batch request should always be list!')

    # Max limit check.
    no_requests = len(requests)

    if no_requests > _settings.MAX_LIMIT:
        raise BadBatchRequest('You can batch maximum of %d requests.' % (_settings.MAX_LIMIT))
    return requests


def get_wsgi_requests(request):
    '''
        For the given batch request, extract the individual requests and create
        WSGIRequest object for each.
    '''
    requests = get_requests_data(request)
    # We could mutate the current request with the respective parameters, but mutation is ghost
    # in the dark, so lets avoid. Construct the new WSGI request object for each request.
    return [construct_wsgi_from_data(request, data) for data in requests]


def is_error(code):
    ''' Check if HTTP status code is error (from django-rest-framework)'''
    return 400 <= code <= 599


def execute_requests(request, sequential_override=False):
    '''
        Execute the requests either sequentially or in parallel based on parallel
        execution setting.
    '''
    if sequential_override:

        # We have to choose a rewriter before we begin processing requests as
        # each request can add new mappings to the rewriter. By default we'll
        # use a JSON-API rewriter, but in the future we may want to make this
        # more dynamic.
        rewriter = JsonApiRewriter()

        with transaction.atomic():
            next_variables = {}
            results = []
            # Get the data to make the requests
            requests = get_requests_data(request)
            for i, request_data in enumerate(requests):
                # Generate the requests using additional data if passed
                wsgi_request, onward_params = construct_wsgi_from_data(
                    request,
                    request_data,
                    replace_params=next_variables,
                    rewriter=rewriter
                )
                result = get_response(wsgi_request)

                # Add the response to the rewriter.
                rewriter.update_mapping(request_data, result)

                results.append(result)
                if is_error(result['status_code']):
                    raise BadBatchRequest(
                        f'Sequential requests failed for request at index {i}: ' +
                        json.dumps(result['body'])
                    )
                # Take the value of any onward passing variables from the response
                for name, accessor_string in onward_params.items():
                    value = None
                    # Allow retrieval of nested values using dot notaion
                    accessors = accessor_string.split('.')
                    if len(accessors):
                        value = result['body']
                    for accessor in accessors:
                        value = value[accessor]
                    if value:
                        next_variables[name] = value
        return results
    else:
        try:
            # Get the Individual WSGI requests.
            wsgi_requests = get_wsgi_requests(request)
        except BadBatchRequest as brx:
            return HttpResponseBadRequest(content=str(brx))

        return _settings.executor.execute(wsgi_requests, get_response)


@csrf_exempt
@require_http_methods(['POST'])
def handle_batch_requests(request, *args, **kwargs):
    '''
        A view function to handle the overall processing of batch requests.
    '''
    batch_start_time = datetime.now()

    # Generate and fire these WSGI requests, and collect the responses
    sequential_override = kwargs.pop('run_sequential', False)
    try:
        response = execute_requests(request, sequential_override)
    except BadBatchRequest as brx:
        return HttpResponseBadRequest(content=str(brx))

    # Evrything's done, return the response.
    resp = HttpResponse(content=json.dumps(response), content_type='application/json')

    if _settings.ADD_DURATION_HEADER:
        resp.__setitem__(
            _settings.DURATION_HEADER_NAME,
            str((datetime.now() - batch_start_time).microseconds / 1000)
        )
    return resp


def handle_sequential_batch_requests(request, *args, **kwargs):
    return handle_batch_requests(request, *args, run_sequential=True, **kwargs)
