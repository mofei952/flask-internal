from werkzeug.wrappers import Request, Response
from werkzeug.local import LocalStack, LocalProxy
from werkzeug.routing import Map, Rule


class FlaskRequest(Request):
    pass


class FlaskResponse(Response):
    default_mimetype = 'text/html'


class _RequestContext(object):
    def __init__(self, app, environ):
        self.app = app
        self.request = app.request_class(environ)
        self.url_adapter = app.url_map.bind_to_environ(environ)


class Flask(object):
    request_class = FlaskRequest
    response_class = FlaskResponse

    def __init__(self, name):
        self.debug = False
        self.name = name
        self.url_map = Map()
        self.view_functions = {}

    def dispatch_request(self):
        endpoint, values = _request_ctx_stack.top.url_adapter.match()
        return self.view_functions[endpoint](**values)

    def route(self, rule, **options):
        def decorator(f):
            if 'endpoint' not in options:
                options['endpoint'] = f.__name__
            self.url_map.add(Rule(rule, **options))
            self.view_functions[options['endpoint']] = f
            return f
        return decorator

    def wsgi_app(self, environ, start_response):
        _request_ctx_stack.push(_RequestContext(self, environ))
        try:
            rv = self.dispatch_request()
            response = self.response_class(rv)
            return response(environ, start_response)
        finally:
            _request_ctx_stack.pop()

    def run(self, host='localhost', port=5000, **options):
        from werkzeug.serving import run_simple
        if 'debug' in options:
            self.debug = options.pop('debug')
        options.setdefault('use_reloader', self.debug)
        options.setdefault('use_debugger', self.debug)
        run_simple(host, port, self, **options)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)


_request_ctx_stack = LocalStack()
current_app = LocalProxy(lambda: _request_ctx_stack.top.app)
request = LocalProxy(lambda: _request_ctx_stack.top.request)

if __name__ == '__main__':
    app = Flask(__name__)

    @app.route('/hello/<name>', methods=['GET'])
    def hello(name):
        return 'hello %s' % name

    app.run(host='0.0.0.0', port=8000, debug=True)
