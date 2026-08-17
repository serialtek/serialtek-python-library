.. _getting_started:

Getting Started
===============

Install the Library
--------------------

.. Note:: ``serialtek`` requires python version 3.10 or newer.

Install the serialtek python library with::

    $ python -m pip install serialtek


Log In to a Kodiak
-------------------

In order to interact with a Kodiak, you first have to log in. The simplest way
is using the CLI.

Discover Kodiaks on the local network
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you don't know your kodiak's hostname or ip address, run ``stcli
discover``. You should see something like this::

    ┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
    ┃ IP Address      ┃ Serial       ┃ URL                               ┃ Alias        ┃
    ┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
    │ 192.168.1.123   │ 000000123    │ https://kodiak-000000123.local    │ Kodiak       │
    └─────────────────┴──────────────┴───────────────────────────────────┴──────────────┘

You can use either the IP address or URL shown here to connect in the next step.

.. note::

    Discovery does not work in all network configurations--especially when
    connecting to the Kodiak requires a VPN. If your Kodiak doesn't show up
    when running this command, you will need to determine the Kodiak's IP
    address another way.

Log in using the CLI
~~~~~~~~~~~~~~~~~~~~~

The ``login`` command is used for logging into a Kodiak. To log in
using a username and password::

    $ stcli login 192.168.1.123 --username my.username

This will prompt for a password and log in to the Kodiak.


Test the connection
~~~~~~~~~~~~~~~~~~~~

Test the connection by running the following command::

    $ stcli active


The output will contain information on the currently active connection.

Use the SerialTek Python Library
--------------------------------

If you have already logged in to a kodiak using the steps above, then you can
just use

.. code-block:: python

    >>> from serialtek import Kodiak
    >>> kodiak = Kodiak()

This will connect to the Kodiak that was most recently connected to using the
`stcli login` cli command. See :py:class:`.Kodiak` for more advanced
authentication.

Access API endpoints
~~~~~~~~~~~~~~~~~~~~~

The main way of interacting with the Kodiak API is through REST API calls.
:py:attr:`.Kodiak.session` allows making API requests while handling the login
session::

    >>> kodiak.session.get("/kodiak/v1/status")

Do more
~~~~~~~

This library also provides helper functions for some device functionality. See:

* :ref:`how_to`
* :ref:`Library API_documentation<package_ref>`
