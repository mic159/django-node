import os
import sys
import atexit
import json
import subprocess
import requests
import uuid
from requests.exceptions import ConnectionError
from django.utils import six
from . import node, npm
from .settings import PATH_TO_NODE, SERVER_DEBUG, NODE_VERSION_REQUIRED, NPM_VERSION_REQUIRED
from .exceptions import NodeServerConnectionError, NodeServerStartError, NodeServerError, ErrorAddingService


class NodeServer(object):
    """
    A persistent Node server which sits alongside the python process
    and responds over HTTP
    """

    debug = SERVER_DEBUG
    path_to_source = os.path.join(os.path.dirname(__file__), 'server.js')
    start_on_init = False
    resolve_dependencies_on_init = True
    shutdown_on_exit = True
    protocol = 'http'
    desired_address = '127.0.0.1'
    desired_port = '0'
    address = None
    port = None
    has_started = False
    has_stopped = False

    _test_endpoint = '/__test__'
    _add_service_endpoint = '/__add_service__'

    _expected_startup_output = 'Started NodeServer'
    _expected_test_output = 'NodeServer running {token}'.format(
        token=uuid.uuid4(),
    )
    _expected_add_service_output = 'Added endpoint {token}'.format(
        token=uuid.uuid4(),
    )

    _process = None
    _startup_output = None
    _server_details_json = None
    _server_details = None

    def __init__(self):
        if self.resolve_dependencies_on_init:
            # Ensure that the external dependencies are met
            node.ensure_version_gte(NODE_VERSION_REQUIRED)
            npm.ensure_version_gte(NPM_VERSION_REQUIRED)

            # Ensure that the required packages have been installed
            npm.install(os.path.dirname(__file__))

        if self.start_on_init:
            self.start()

    def start(self):
        if self.shutdown_on_exit:
            atexit.register(self.stop)

        cmd = (
            PATH_TO_NODE,
            self.path_to_source,
            '--address', self.desired_address,
            '--port', self.desired_port,
            '--expected-startup-output', self._expected_startup_output,
            '--test-endpoint', self._test_endpoint,
            '--expected-test-output', self._expected_test_output,
            '--add-service-endpoint', self._add_service_endpoint,
            '--expected-add-service-output', self._expected_add_service_output,
        )

        self.log('Starting process with {cmd}'.format(cmd=cmd))

        # While rendering templates Django will silently ignore some types of exceptions,
        # so we need to intercept them and raise our own class of exception
        try:
            # TODO: set NODE_ENV. See `env` arg https://docs.python.org/2/library/subprocess.html#popen-constructor
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except (TypeError, AttributeError):
            msg = 'Failed to start server with {arguments}'.format(arguments=cmd)
            six.reraise(NodeServerStartError, NodeServerStartError(msg), sys.exc_info()[2])

        # Check the first line of the server's output to ensure that it has started successfully
        self._startup_output = self._process.stdout.readline().decode()
        if self._startup_output.strip() != self._expected_startup_output:
            self._startup_output += self._process.stdout.read().decode()
            self.stop()
            raise NodeServerStartError(
                'Error starting server: {startup_output}'.format(
                    startup_output=self._startup_output
                )
            )

        server_details_json = self._process.stdout.readline()
        self._server_details_json = server_details_json.decode()
        self._server_details = json.loads(self._server_details_json)

        # If the server is defining its own address or port, we need to record it
        self.address = self._server_details['address']
        self.port = self._server_details['port']

        self.has_started = True
        self.has_stopped = False

        # Ensure that we can connect to the server over the network
        if not self.test():
            self.stop()
            raise NodeServerStartError(
                'Cannot test server to determine if startup successful. Tried "{test_url}"'.format(
                    test_url=self.get_test_url()
                )
            )

        self.log('Started process')

    def ensure_started(self):
        if not self.has_started:
            self.start()

    def stop(self):
        if self._process is not None and not self.has_stopped:
            self._process.terminate()
            self.log('Terminated process')

        self.has_stopped = True
        self.has_started = False
        self.address = None
        self.port = None

    def get_server_url(self):
        if self.protocol and self.address and self.port:
            return '{protocol}://{address}:{port}'.format(
                protocol=self.protocol,
                address=self.address,
                port=self.port,
            )

    def absolute_url(self, url):
        separator = '/' if not url.startswith('/') else ''
        return '{server_url}{separator}{url}'.format(
            server_url=self.get_server_url(),
            separator=separator,
            url=url,
        )

    def get_test_url(self):
        return self.absolute_url(self._test_endpoint)

    def _clean_error_message(self, html):
        # TODO: replace this with an actual decoder, see: http://stackoverflow.com/a/2087433
        # Convert the error message from HTML to plain text
        html = html.replace('<br>', '\n')
        html = html.replace('&nbsp;', ' ')
        html = html.replace('&quot;', '"')
        # Remove multiple spaces
        html = ' '.join(html.split())
        return html

    def _check_response(self, response, url):
        if response.status_code != 200:
            error_message = self._clean_error_message(response.text)
            raise NodeServerError(
                'Error at {url}: {error_message}'.format(
                    url=url,
                    error_message=error_message,
                )
            )

        return response

    def get_server_name(self):
        return self.__class__.__name__

    def log(self, message):
        # TODO: replace print with django's logger
        if self.debug:
            print('{server_name} [Address: {server_url}] {message}'.format(
                server_name=self.get_server_name(),
                server_url=self.get_server_url(),
                message=message,
            ))

    def test(self):
        if self.address is None or self.port is None:
            return False

        test_url = self.get_test_url()

        self.log('Testing server at {test_url}'.format(test_url=test_url))

        try:
            response = requests.get(test_url)
        except ConnectionError:
            return False

        if response.status_code != 200:
            return False

        return response.text == self._expected_test_output

    def get_service(self, endpoint):
        def service(**kwargs):
            return self.get(endpoint, params=kwargs)
        service.__name__ = '{server_name} service {endpoint}'.format(
            server_name=self.get_server_name(),
            endpoint=endpoint,
        )
        return service

    def add_service(self, endpoint, path_to_source):
        self.ensure_started()

        self.log('Adding service at "{endpoint}" with source "{path_to_source}"'.format(
            endpoint=endpoint,
            path_to_source=path_to_source,
        ))

        add_service_url = self.absolute_url(self._add_service_endpoint)

        try:
            response = requests.post(add_service_url, data={
                'endpoint': endpoint,
                'path_to_source': path_to_source,
            })
        except ConnectionError as e:
            six.reraise(NodeServerConnectionError, NodeServerConnectionError(*e.args), sys.exc_info()[2])

        response = self._check_response(response, add_service_url)

        if response.text != self._expected_add_service_output:
            error_message = self._clean_error_message(response.text)
            raise ErrorAddingService(error_message)

        return self.get_service(endpoint=endpoint)

    def get(self, endpoint, params=None):
        self.ensure_started()

        self.log('Sending request to endpoint "{url}" with params "{params}"'.format(
            url=endpoint,
            params=params,
        ))

        absolute_url = self.absolute_url(endpoint)

        try:
            response = requests.get(absolute_url, params=params)
        except ConnectionError as e:
            six.reraise(NodeServerConnectionError, NodeServerConnectionError(*e.args), sys.exc_info()[2])

        return self._check_response(response, endpoint)