from werkzeug.exceptions import abort, InternalServerError, HTTPException, default_exceptions
from werkzeug.wrappers import Request, Response
from werkzeug.routing import Map, Rule
from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.local import LocalStack, LocalProxy

_request_ctx_stack = LocalStack()
current_app = LocalProxy(lambda: _request_ctx_stack.top.app)
request = LocalProxy(lambda: _request_ctx_stack.top.request)
session = LocalProxy(lambda: _request_ctx_stack.top.session)


class _RequestContext(object):
    def __init__(self, app, environ):
        self.app = app
        self.request = app.request_class(environ)
        self.session = app.open_session(self.request)
        self.url_adapter = app.url_map.bind_to_environ(environ)

    def __enter__(self):
        _request_ctx_stack.push(self)

    def __exit__(self, exc_type, exc_value, tb):
        _request_ctx_stack.pop()


class FlaskRequest(Request):
    pass


class FlaskResponse(Response):
    default_mimetype = 'text/html'


class ConfigAttribute(object):
    def __init__(self, name):
        self.__name__ = name

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        rv = obj.config[self.__name__]
        return rv

    def __set__(self, obj, value):
        obj.config[self.__name__] = value


class Flask(object):
    request_class = FlaskRequest
    response_class = FlaskResponse

    secret_key = ConfigAttribute('SECRET_KEY')
    session_cookie_name = ConfigAttribute('SESSION_COOKIE_NAME')

    def __init__(self):
        self.debug = False
        self.url_map = Map()
        self.view_functions = {}
        self.config = {}
        self.blueprints = {}
        self.error_handlers = {}

    def dispatch_request(self):
        endpoint, values = _request_ctx_stack.top.url_adapter.match()
        return self.view_functions[endpoint](**values)

    def register_blueprint(self, blueprint, **options):
        self.blueprints[blueprint.name] = blueprint
        blueprint.register(self, **options)

    def add_url_rule(self, rule, endpoint, view_func, **options):
        options['endpoint'] = endpoint
        self.url_map.add(Rule(rule, **options))
        self.view_functions[endpoint] = view_func

    def route(self, rule, **options):
        def decorator(f):
            endpoint = options.pop('endpoint', f.__name__)
            self.add_url_rule(rule, endpoint, f, **options)
            return f
        return decorator

    def errorhandler(self, code):
        def decorator(f):
            self.error_handlers[code] = f
        return decorator

    def open_session(self, request):
        return SecureCookie.load_cookie(request,
                                        key=self.session_cookie_name,
                                        secret_key=self.secret_key)

    def save_session(self, response):
        session.save_cookie(response, key=self.session_cookie_name)

    def make_response(self, response):
        self.save_session(response)
        return response

    def request_context(self, environ):
        return _RequestContext(self, environ)

    def test_request_context(self, *args, **kwargs):
        from werkzeug.test import create_environ
        return self.request_context(create_environ(*args, **kwargs))

    def test_client(self):
        from werkzeug.test import Client
        return Client(self, self.response_class, use_cookies=True)

    def wsgi_app(self, environ, start_response):
        with self.request_context(environ):
            try:
                print('user: %s' % session.setdefault('user', 'none'))
                print('total_request: %d' % session.setdefault('total_request', 0))
                session['total_request'] += 1

                rv = self.dispatch_request()
                response = self.finalize_request(rv)
            except Exception as e:
                response = self.handle_exception(e)
            return response(environ, start_response)

    def handle_exception(self, e):
        code = e.code if isinstance(e, HTTPException) else None
        handler = self.error_handlers.get(code)
        if not handler:
            exception = default_exceptions.get(code)
            if exception:
                return exception
        if not handler:
            return InternalServerError(e)
        return self.finalize_request(handler(e), e.code)

    def finalize_request(self, rv, status=200):
        response = self.response_class(rv, status=status)
        response = self.make_response(response)
        return response

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)

    def run(self, host='localhost', port=5000, **options):
        if 'debug' in options:
            self.debug = options.pop('debug')

        options.setdefault('use_reloader', self.debug)
        options.setdefault('use_debugger', self.debug)

        from werkzeug.serving import run_simple
        run_simple(host, port, self, **options)


class BlueprintSetupState(object):
    def __init__(self, blueprint, app, **options):
        self.blueprint = blueprint
        self.app = app
        self.url_prefix = options.get('url_prefix',
                                      '/%s' % self.blueprint.name)

    def add_url_rule(self, rule, endpoint, view_func, **options):
        rule = '/'.join((self.url_prefix, rule.lstrip('/')))
        endpoint = '%s.%s' % (self.blueprint.name, endpoint)
        self.app.add_url_rule(rule, endpoint, view_func, **options)


class Blueprint(object):
    def __init__(self, name):
        self.name = name
        self.deferred_functions = []

    def register(self, app, **options):
        state = BlueprintSetupState(self, app, **options)
        for deferred in self.deferred_functions:
            deferred(state)

    def record(self, func):
        self.deferred_functions.append(func)

    def add_url_rule(self, rule, endpoint, view_func, **options):
        self.record(lambda s: s.add_url_rule(rule, endpoint, view_func,
                                             **options))

    def route(self, rule, **options):
        def decorator(f):
            endpoint = options.pop("endpoint", f.__name__)
            self.add_url_rule(rule, endpoint, f, **options)
            return f
        return decorator


if __name__ == '__main__':
    bp = Blueprint('foo')

    @bp.route('/hello/<user>', methods=['GET'])
    def foo_hello(user):
        session['user'] = user
        return '[foo] hello %s' % user

    app = Flask()
    app.config = {
        'SECRET_KEY': 'dangerous',
        'SESSION_COOKIE_NAME': 'flask_session'
    }

    @app.route('/favicon.ico', methods=['GET'])
    def favicon():
        return '🙈'

    @app.route('/hello/<user>', methods=['GET'])
    def hello(user):
        session['user'] = user
        abort(404)
        # abort(405)
        # raise ValueError('value error aaa')
        # return '[app] hello %s' % user

    @app.errorhandler(404)
    def page_not_found(error):
        return 'page not found'

    app.register_blueprint(bp)

    app.run('0.0.0.0', 5000, debug=True)
