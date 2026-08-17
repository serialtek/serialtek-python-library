from serialtek import FieldDecodes, Filter, Kodiak
from serialtek._sample_tests import expect_output, init, print

# fmt: off

def test_main():
    init()
    kodiak = Kodiak()

    event = None

    # create-a-cursor
    trace_path = "/media/SATADrive0/serialtek-sample-traces/nvme-write.sttrace"
    with kodiak.open_trace(trace_path) as trace:
        with trace.open_cursor() as cursor:
            # `cursor` is now pointing to the start of the trace
            for event in cursor.get(9):
                print(f"{event.timestamp}  <{event.type}>")
            ##

            expect_output("output-1", """
            000.000.002.201.625  <eds>
            000.000.002.202.250  <os>
            000.000.002.392.625  <eds>
            000.000.002.393.250  <os>
            000.000.005.216.000  <eds>
            000.000.005.216.625  <os>
            000.000.005.407.000  <eds>
            000.000.005.407.625  <os>
            000.000.007.430.750  <dllp>
            """)

            # dllp-repr
            print(repr(event))
            ##

            expect_output("dllp-repr", """
            {'type': 'dllp', 'channel': 0, 'timestamp': 7430750, 'eid': 0, 'subtype': 144, 'speed': 3, 'width': 2, 'payload': 'kk&594EH;H', 'duration': 1000, 'link_mode': 'unknown', 'start_lane': 0, 'page_timeslot': 14624}
            """)

            # filter-in
            cursor.set_filter(Filter.In({
                "data.tlp.mwr32": True,
            }))
            for event in cursor.get(10, start=0): # Start from the beginning again
                print(f"{event.timestamp}  <{event.type}>")
            ##

            expect_output("filter-in", """
            000.562.838.351.000  <tlp>
            000.567.415.702.500  <tlp>
            000.567.432.663.375  <tlp>
            000.567.446.783.000  <tlp>
            000.567.517.665.375  <tlp>
            000.567.545.154.125  <tlp>
            000.567.558.257.625  <tlp>
            000.567.631.458.000  <tlp>
            000.567.645.688.875  <tlp>
            000.567.656.627.125  <tlp>
            """)

            # decodes

            # Here we're using a more specific filter: only looking at TLP reads
            cursor.set_filter(Filter.In({"data.tlp.mrd": True}))

            # You can specify decodes either by name or by id
            cursor.set_decodes(FieldDecodes(
                {"events":{"tlp":[2717525879]}}, # "Type"
                {"events":{"tlp":["Address"]}}
            ))

            for event in cursor.get(10, start=0):
                # Similarly, look them up by name or ID: it doesn't have to be the same
                # as what you used in set_decodes
                type_decode = event.fields.get("Type")
                addr = event.fields.get("Address")
                print(f"{event.timestamp}  Type: {type_decode.decoding}  Address: 0x{addr.value:X}")
            ##

            expect_output("decodes", """
            000.567.335.468.500  Type: MRd  Address: 0x10AA9AD00
            000.567.447.036.375  Type: MRd  Address: 0x10AA9AD40
            000.567.558.507.500  Type: MRd  Address: 0x10AA9AD80
            000.567.656.875.000  Type: MRd  Address: 0x10AA9ADC0
            000.567.754.602.625  Type: MRd  Address: 0x10AA9AE00
            000.567.838.966.250  Type: MRd  Address: 0x10AA9AE40
            000.567.851.226.875  Type: MRd  Address: 0x10AA9AE80
            000.567.860.188.625  Type: MRd  Address: 0x10AA9AEC0
            000.567.869.030.625  Type: MRd  Address: 0x10AA9AF00
            000.567.877.411.500  Type: MRd  Address: 0x10AA9AF40
            """)

        # pcie-builder
        print("PCIe Transactions:")
        with trace.open_pcie_builder() as builder:
            for txn in builder.get(10):
                print(f"  {txn.timestamp}  {txn.raw_data['pcie_type']}")
        ##

        expect_output("pcie", """
        PCIe Transactions:
          000.562.838.351.000  posted
          000.567.283.096.375  posted
          000.567.335.468.500  non-posted
          000.567.415.229.250  posted
          000.567.415.265.750  posted
          000.567.415.503.375  posted
          000.567.415.702.500  posted
          000.567.432.663.375  posted
          000.567.446.783.000  posted
          000.567.447.036.375  non-posted
        """)

        # nvme-builder
        print("NVMe Transactions:")
        with trace.open_nvme_builder() as builder:
            for txn in builder.get(10):
                print(f"  {txn.timestamp}  {txn.raw_data.get('nvme_type', txn.type)}")
        ##

        expect_output("nvme", """
        NVMe Transactions:
          000.562.838.351.000  NVMe Submission Doorbell
          000.567.283.096.375  pcie
          000.567.335.468.500  NVMe I/O
          000.567.415.702.500  NVMe MSI Vector
          000.567.432.663.375  NVMe Completion Doorbell
          000.567.446.783.000  NVMe Submission Doorbell
          000.567.447.036.375  NVMe I/O
          000.567.517.665.375  NVMe MSI Vector
          000.567.545.154.125  NVMe Completion Doorbell
          000.567.558.257.625  NVMe Submission Doorbell
        """)

if __name__ == "__main__":
    test_main()
