.. _guide_lib_iterating_events:

Iterating Over a Large Number of Events
=======================================

A trace can contain hundreds of millions of events. Attempting to iterate
through all of these events can take a long time. Some actions can be taken to
speed this up:

Apply a filter
---------------

The most effective way to speed up iteration is often applying a filter: This
will prevent events that aren't needed from even being sent over the network
connection. See :py:class:`serialtek.filter.Filter` and :ref:`apply_filter`.

Exclude unneeded fields
-----------------------

The slowest part of iterating over so many events is simply sending that many
bytes over the network. You can reduce the size of each individual event by
excluding any unneeded fields. Methods like :py:meth:`.CursorBase.get` accept
``fields`` and ``not_fields`` arguments that can be used to limit the fields
that are included in events. If ``fields`` is specified, only the fields given
will be included. If ``not_fields`` is specified, those fields will not be
included in events. The ``type``, ``timestamp``, and ``channel`` fields are
always included.


.. literalinclude:: test_iteration-strategies.py
    :language: python
    :start-after: # fields
    :end-before: ##
    :dedent:

.. literalinclude:: test_iteration-strategies.py
    :start-after: "fields"
    :end-before: """)
    :dedent:

Fields are only parsed from the event when you access them, so excluding a
field with ``fields``/``not_fields`` never causes an error on its own.
Accessing an excluded field afterwards will raise an :py:exc:`AttributeError`:

.. literalinclude:: test_iteration-strategies.py
    :language: python
    :start-after: # excluded-field-access
    :end-before: ##
    :dedent:

.. literalinclude:: test_iteration-strategies.py
    :start-after: "excluded-field-access"
    :end-before: """)
    :dedent:
