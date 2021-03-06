django-node
===========

[![Build Status](https://travis-ci.org/markfinger/django-node.svg?branch=master)](https://travis-ci.org/markfinger/django-node)

django-node provides a way of hosting persistent JS services which are easily accessible from a django application.

Using services opens up a number of possibilites which are difficult or impossible to perform in a typical Django application, for example:
- Server-side rendering of JS (Isomorphic JavaScript)
- Background processes, such as file watchers
- WebSockets

Behind the scenes, django-node will connect to either a pre-existing instance of [django-node-server](https://github.com/markfinger/django-node-server) or will create an instance as a subprocess.

Additionally, django-node provides a number of bindings and utilites to assist with integrating Node and NPM into a Django application.

**Please note** that django-node is a work in progress. In particular, the JS services API is prone to change as issues are identified and fixed.


Basic documentation
-------------------

- [Basic usage](#basic-usage)
- [Installation](#installation)
- [Examples](#examples)
- [Running the tests](#running-the-tests)


API documentation
-----------------

- [JS services](docs/js_services.md)
- [Managment commands](docs/management_commands.md)
- [NodeServer](docs/node_server.md)
- [Node](docs/node.md)
- [NPM](docs/npm.md)
- [Settings](docs/settings.md)


Basic usage
-----------

To create a JS service, define a function and export it as a module. 

```javascript
// my_app/hello_world_service.js

var service = function(request, response) {
	var name = request.query.name;
	response.send(
	    'Hello, ' + name + '!';
	);
};

module.exports = service;
```

Create a python interface to your service by inheriting from `django_node.base_service.BaseService`.

```python
# my_app/services.py

import os
from django_node.base_service import BaseService

class HelloWorldService(BaseService):
    # An absolute path to a file containing the JS service
    path_to_source = os.path.join(os.path.dirname(__file__), 'hello_world_service.js')

    def greet(self, name):
        response = self.send(name=name)
        return response.text
```

Configure django-node to load your service by adding the service's module as a 
dotstring to the `DJANGO_NODE['SERVICES']` setting.

```python
# in settings.py

DJANGO_NODE = {
    'SERVICES': (
    	'my_app.services',
    ),
}
```

During django-node's initialisation, the modules defined in `DJANGO_NODE['SERVICES']` are 
imported and all of the classes contained which inherit from `django_node.base_service.BaseService` will be 
loaded into a [django-node-server](https://github.com/markfinger/django-node-server) instance.

You can now send a request to your service and receive a response.

```python
hello_world_service = HelloWorldService()

greeting = hello_world_service.greet('World')

print(greeting)  # prints 'Hello, World!'
```

Besides JS services, django-node also provides a number of bindings and utilities for
interacting with Node and NPM.

```python
import os
from django_node import node, npm

# Run a particular file with Node.js
stderr, stdout = node.run('/path/to/some/file.js', '--some-argument', 'some_value')

# Call `npm install` within the current file's directory
stderr, stdout = npm.install(os.path.dirname(__file__))
```


Installation
------------

```bash
pip install django-node
```

Add `'django_node'` to your `INSTALLED_APPS`

```python
INSTALLED_APPS = (
    # ...
    'django_node',
)
```


Examples
--------

The following apps make heavy use of django-node and illustrate how to perform non-trivial tasks.

- [django-react](http://github.com/markfinger/django-react)
- [django-webpack](http://github.com/markfinger/django-webpack)


Running the tests
-----------------

```bash
mkvirtualenv django-node
pip install -r requirements.txt
python runtests.py
```
