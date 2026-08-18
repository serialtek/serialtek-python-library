"""Example of capturing a trace using trigger-based stop.

In order to use this example, you will need to create capture settings. See
http://serialtek-python-library.readthedocs.io/en/latest/library/howto/library-capture.html
for details.

The created capture settings should use an automatic stop mode, ie "Stop When Full" or
"Trigger".
"""
import time

from serialtek import Kodiak

# Log into a kodiak using `stcli login` before running this script, and this line will
# use that session.
kodiak = Kodiak()
capture_settings_path = "CaptureSettings-trigger-configured.json"
save_path = kodiak.Path("/media/NVMeDrive0/example-auto-stop-capture.sttrace")

with kodiak.lock():
    cap = kodiak.start_capture(capture_settings_path)

    # Depending on what you are capturing, you may want to manually trigger the capture:
    time.sleep(5)
    cap.trigger()

    # Whether you are manually triggering or just waiting for the trigger to occur, you
    # need to wait for the capture to finish before acessing the trace:
    cap.join()

    with cap.open_trace() as trace:
        trace.save(save_path)
