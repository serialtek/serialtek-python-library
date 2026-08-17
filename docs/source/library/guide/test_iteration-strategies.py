from serialtek import Kodiak
from serialtek._sample_tests import expect_output, init, print

# fmt: off

def test_main():
    init()
    kodiak = Kodiak()

    event = None

    # fields
    trace_path = "/media/SATADrive0/serialtek-sample-traces/nvme-write.sttrace"
    with kodiak.open_trace(trace_path) as trace:
        with trace.open_cursor() as cursor:
            # This is the timestamp of a DLLP that we'll use for the examples
            start_ts = "000.000.007.430.750"

            # This is the "default" case, where all fields in the response are included.
            for event in cursor.get(1, start=start_ts):
                print(f"With all fields:")
                print(f"  {event!r}")

            # You can exclude specific fields with `not_fields`
            for event in cursor.get(1, not_fields={"payload", "flit_timestamps"}, start=start_ts):
                print(f"With excluded fields:")
                print(f"  {event!r}")

            # Or get only specific fields with `fields`
            for event in cursor.get(1, fields={"payload", "speed", "width"}, start=start_ts):
                print(f"With included fields:")
                print(f"  {event!r}")

            # Using `fields` and leaving it empty excludes all non-essential fields
            for event in cursor.get(1, fields={}, start=start_ts):
                print(f"With minimal fields:")
                print(f"  {event!r}")
            ##

            expect_output("fields", """
            With all fields:
              {'type': 'dllp', 'channel': 0, 'timestamp': 7430750, 'eid': 0, 'subtype': 144, 'speed': 3, 'width': 2, 'payload': 'kk&594EH;H', 'duration': 1000, 'link_mode': 'unknown', 'start_lane': 0, 'page_timeslot': 14624}
            With excluded fields:
              {'type': 'dllp', 'channel': 0, 'timestamp': 7430750, 'eid': 0, 'subtype': 144, 'speed': 3, 'width': 2, 'duration': 1000, 'link_mode': 'unknown', 'start_lane': 0, 'page_timeslot': 14624}
            With included fields:
              {'type': 'dllp', 'channel': 0, 'timestamp': 7430750, 'eid': 0, 'speed': 3, 'width': 2, 'payload': 'kk&594EH;H'}
            With minimal fields:
              {'type': 'dllp', 'channel': 0, 'timestamp': 7430750, 'eid': 0}
            """)

            # excluded-field-access
            for event in cursor.get(1, fields={}, start=start_ts):
                try:
                    print(event.subtype)
                except AttributeError as e:
                    print(f"AttributeError: {e}")
            ##

            expect_output("excluded-field-access", """
            AttributeError: subtype
            """)

if __name__ == "__main__":
    test_main()
