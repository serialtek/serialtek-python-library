import time

from serialtek import Kodiak

# Change these values to match your setup.
kodiak = Kodiak()
capture_settings_path = "CaptureSettings-manual-stop.json"
save_path = kodiak.Path("/media/NVMeDrive0/example-manual-stop-capture.sttrace")


def generate_my_traffic():
    # This is where you would do something to generate the traffic you want to capture:
    # write to a drive, trigger an action on a remote machine connected to the kodiak,
    # etc. Since this is a generic example, we'll just wait a few seconds to simulate
    # something happening.
    time.sleep(5)

with kodiak.lock():
    with kodiak.start_capture(capture_settings_path) as cap:
        generate_my_traffic()

    with cap.open_trace() as trace:
        trace.save(save_path)
