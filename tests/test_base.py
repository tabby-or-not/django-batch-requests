'''
@author: Rahul Tanwani

@summary: Contains base test case for reusable test methods.
'''
import json

from batch_requests.settings import br_settings as settings
from django.test import TestCase


class TestBase(TestCase):
    '''
        Base class for all reusable test methods.
    '''

    def assert_reponse_compatible(self, ind_resp, batch_resp):
        '''
            Assert if the response of independent request is compatible with
            batch response.
        '''
        # Remove duration header to compare.
        if settings.ADD_DURATION_HEADER:
            del batch_resp['headers'][settings.DURATION_HEADER_NAME]
            del batch_resp['headers']['request_url']

        self.assertDictEqual(ind_resp, batch_resp, 'Compatibility is broken!')

    def headers_dict(self, headers):
        '''
            Converts the headers from the response in to a dict.
        '''
        return dict(headers.values())

    def prepare_response(self, status_code, body, headers):
        '''
            Returns a dict of all the parameters.
        '''
        return {
            'status_code': status_code,
            'body': body.decode('utf-8'),
            'headers': self.headers_dict(headers),
        }

    def _batch_request(self, method, path, data, headers={}):
        '''
            Prepares a batch request.
        '''
        return {'url': path, 'method': method, 'headers': headers, 'body': data}

    def make_a_batch_request(self, *args):
        '''
            Makes a batch request using django client.
        '''
        batch_request = json.dumps({'batch': [self._batch_request(*args)]})
        return self.client.post('/api/v1/batch/', batch_request, content_type='application/json')

    def make_multiple_batch_request(self, requests):
        '''
            Makes multiple batch request using django client.
        '''
        batch_requests = json.dumps({'batch': [self._batch_request(*args) for args in requests]})
        return self.client.post('/api/v1/batch/', batch_requests, content_type='application/json')
