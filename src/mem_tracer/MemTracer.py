from m5.objects.ClockedObject import ClockedObject
from m5.params import *
from m5.SimObject import cxxMethod


class MemTracer(ClockedObject):
    type = "MemTracer"
    cxx_header = "mem_tracer/mem_tracer.hh"
    cxx_class = "gem5::MemTracer"

    mem_side = RequestPort("This port sends requests and receives responses")
    cpu_side = ResponsePort("This port receives requests and sends responses")

    trace_file = Param.String(
        "dram_trace.bin", "Path to the binary output trace file"
    )

    @cxxMethod
    def startTrace(self):
        pass

    @cxxMethod
    def stopTrace(self):
        pass
