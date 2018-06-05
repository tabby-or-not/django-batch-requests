import json
import uuid

from batch_requests.jsonapi import JsonApiRewriter
from tests.test_base import TestBase


class TestJsonApiRewriter(TestBase):
    def setUp(self):
        self.rewriter = JsonApiRewriter()
        self.id = str(uuid.uuid4())
        self.requests = [
            {
                'method': 'post',
                'body': json.dumps({
                    'data': {
                        'type': 'A',
                        'id': self.id
                    }
                })
            },
            {
                'method': 'post',
                'body': json.dumps({
                    'data': {
                        'type': 'B',
                        'id': str(uuid.uuid4()),
                        'relationships': {
                            'f0': {
                                'data': {
                                    'type': 'A',
                                    'id': self.id
                                }
                            }
                        }
                    }
                })
            }
        ]
        self.responses = [
            {
                'status_code': 201,
                'body': {
                    'data': {
                        'type': 'A',
                        'id': 1
                    }
                }
            },
            {
                'status_code': 201,
                'body': {
                    'data': {
                        'type': 'B',
                        'id': 2
                    }
                }
            }
        ]

    def test_basic_posts(self):
        """ Subsequent posts must rewrite relationships.
        """
        for request, response in zip(self.requests, self.responses):
            self.rewriter.rewrite_request(request)
            self.rewriter.update_mapping(request, response)
        self.assertEqual(
            self.requests[1]['body']['data']['relationships']['f0']['data']['id'],
            self.responses[0]['body']['data']['id']
        )
