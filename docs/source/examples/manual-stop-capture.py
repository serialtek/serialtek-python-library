"""Example of capturing a trace using script-triggered stop.

In order to use this example, you will need to create capture settings. See
http://serialtek-python-library.readthedocs.io/en/latest/library/howto/library-capture.html
for details.

The created capture settings should use "Manual" stop mode.
"""
import time

from serialtek import Kodiak

# Log into a kodiak using `stcli login` before running this script, and this line will
# use that session.
kodiak = Kodiak()
capture_settings_path = "CaptureSettings-manual-stop.json"
save_path = kodiak.Path("/media/NVMeDrive0/example-manual-stop-capture.sttrace")

with kodiak.lock():
    # Start capture on the kodiak. Using the with block here will automatically stop
    # capture at the end of the block.
    with kodiak.start_capture(capture_settings_path) as cap:
        # This is where you would do something to generate the traffic you want to capture:
        # write to a drive, trigger an action on a remote machine connected to the kodiak,
        # etc. Since this is a generic example, we'll just wait a few seconds to simulate
        # something happening.
        time.sleep(5)

    with cap.open_trace() as trace:
        trace.save(save_path)
