.. _ht_lib_capture:

Capture a Trace with the Library
================================

Create Capture Settings
-----------------------

.. include:: ../../snippets.rst
    :start-after: .. create-capture-settings
    :end-before: .. end

Lock the Kodiak
------------------

Starting, stopping, or triggering the Kodiak requires holding the lock, to
prevent multiple users from conflicting. Take the lock with :py:meth:`.Kodiak.lock()`:

.. code-block:: python

    with kodiak.lock():
        # perform actions with the lock...
    # unlock() is called automatically when exiting the block.

Start and Stop the Capture
--------------------------

There are multiple ways that you might want to control the capture, depending on
how the capture is configured to stop.

Manual stop modes
^^^^^^^^^^^^^^^^^^

When a capture is configured for manual stop, it needs to be stopped via an API
call in the same way it was started. This usually means that the code will be
starting the capture, then communicating with some other device to initiate the
behavior to capture, and stopping the capture when that has completed.

.. code-block:: python

    # Use the CaptureSettings.json downloaded from the web UI.
    cap = kodiak.start_capture("path/to/CaptureSettings.json")
    generate_my_traffic()
    cap.stop()

The :py:class:`~serialtek.LiveCapture` object returned by
:py:meth:`.Kodiak.start_capture` can be used as a context manager to support
this pattern a little more simply:

.. code-block:: python

    with kodiak.start_capture("path/to/CaptureSettings.json") as cap:
        generate_my_traffic()
    # cap.stop() is called when exiting the context.

This also has the advantage of ensuring that if something goes wrong and
:py:meth:`generate_my_traffic()` raises an exception,
:py:meth:`~.LiveCapture.stop` will still be called.

.. dropdown:: :icon:`file code` Example: Manually stop capture

    :download:`manual-stop-capture.py <../../examples/manual-stop-capture.py>`

    .. literalinclude:: ../../examples/manual-stop-capture.py
        :language: python

Automatic Stop Modes
^^^^^^^^^^^^^^^^^^^^^

When the capture is configured to stop when a buffer is full or on a trigger,
:py:meth:`.LiveCapture.join` can be used to wait for the capture to complete:

.. code-block:: python

    cap = kodiak.start_capture("path/to/CaptureSettings.json")
    cap.join()

When the capture is configured in trigger mode, the capture can optionally be
triggerred directly over the API. In this case, you still need to call
:py:meth:`~.LiveCapture.join` to wait for the capture to finish after the
trigger:

.. code-block:: python

    cap = kodiak.start_capture("path/to/CaptureSettings.json")
    cap.trigger()
    cap.join()

.. dropdown:: :icon:`file code` Example: Wait for capture to automatically stop

    :download:`auto-stop-capture.py <../../examples/auto-stop-capture.py>`

    .. literalinclude:: ../../examples/auto-stop-capture.py
        :language: python

Access the Resulting Trace
---------------------------

Once the capture is complete, the capture's data becomes available as the Live
Trace, which can be accessed or saved with :py:meth:`~.LiveCapture.open_trace`.

.. code-block:: python

    with cap.open_trace() as trace:
        trace.save("/media/NVMeDrive0/file-name.sttrace")

Opening the trace requires waiting for the trace post-processing to finish, so
this call may take some time to complete.

.. include:: ../../snippets.rst
    :start-after: .. live-trace-lock-warning
    :end-before: .. end

Both of the above examples include code to open and save the resulting trace.
