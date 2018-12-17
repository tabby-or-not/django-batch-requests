import json


class JsonApiRewriter:
    """ Rewrite JSON-API requests.

    JSON-API allows posting resources with UUIDs as IDs. This allows
    for simultaneously posting a creation and another resource that
    uses the first resource as a relationship. This rewriter supports
    replacing the UUID value in subsequent relationships with the
    DB level ID.
    """
    def __init__(self):

        # Cache the generated mappings.
        self.mapping = {}

        # Only rewrite a request if the method matches one of these.
        self.rewrite_methods = {'post', 'put', 'patch', 'delete'}

        # Only incorporate a mapping if the response method and status
        # code matches one of the following.
        self.update_methods = {'post', 'put', 'patch'}
        self.update_status_codes = {200, 201}

    def rewrite_request(self, request):
        """ Called first to rewrite a JSON-API request.
        """
        if not self.should_rewrite(request):
            return request
        body = request.get('body', None)
        if body is not None:
            body = json.loads(body)
            self.rewrite_body(body)
            request['body'] = body

    def rewrite_body(self, body):
        data = body.get('data', {})
        self.rewrite_main(data)
        for name, rel in data.get('relationships', {}).items():
            self.rewrite_relationship(name, rel)

    def rewrite_main(self, data):
        self.rewrite_relation(data)

    def rewrite_relationship(self, name, relationship):
        data = relationship.get('data', {})
        if not isinstance(data, list):
            data = [data]
        for related in data:
            self.rewrite_relation(related)

    def rewrite_relation(self, relation):
        if relation is None:
            return
        mapped_id = self.map_relation_id(relation)
        if mapped_id:
            relation['id'] = mapped_id

    def map_relation_id(self, relation):
        type, id = relation.get('type'), relation.get('id')
        return self.mapping.get(type, {}).get(id)

    def update_mapping(self, request, response):
        if not self.should_update(request, response):
            return
        req_body = request.get('body', None)
        rsp_body = response.get('body', None)
        if req_body is None or rsp_body is None:
            return
        req_data = req_body.get('data', {})
        rsp_data = rsp_body.get('data', {})
        if 'id' in req_data and 'id' in rsp_data:
            self.mapping.setdefault(
                req_data['type'], {}
            )[req_data['id']] = rsp_data['id']

    def should_rewrite(self, request):
        method = request.get('method', '')
        return method.lower() in self.rewrite_methods

    def should_update(self, request, response):
        method = request.get('method', '')
        return (
            method.lower() in self.update_methods and
            response.get('status_code') in self.update_status_codes
        )
