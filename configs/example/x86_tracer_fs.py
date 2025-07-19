from typing import (
    List,
    Sequence,
    Tuple,
)

from m5.objects import (
    AddrRange,
    MemCtrl,
    MemInterface,
    MemTracer,
    Port,
)

from gem5.coherence_protocol import CoherenceProtocol
from gem5.components.boards.abstract_board import AbstractBoard
from gem5.components.boards.x86_board import X86Board
from gem5.components.cachehierarchies.ruby.mesi_two_level_cache_hierarchy import (
    MESITwoLevelCacheHierarchy,
)
from gem5.components.memory.abstract_memory_system import AbstractMemorySystem
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_switchable_processor import (
    SimpleSwitchableProcessor,
)
from gem5.isas import ISA
from gem5.resources.resource import obtain_resource
from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires

requires(
    isa_required=ISA.X86,
    coherence_protocol_required=CoherenceProtocol.MESI_TWO_LEVEL,
    kvm_required=True,
)


class TracedMemorySystem(AbstractMemorySystem):
    def __init__(self, size: str):
        super().__init__()
        self.tracer = MemTracer(trace_file="fs_mem_trace.bin")
        self.mem_system = SingleChannelDDR3_1600(size=size)

    def incorporate_memory(self, board: AbstractBoard) -> None:
        self.mem_system.incorporate_memory(board)
        self.tracer.mem_side = self.mem_system.get_memory_controllers()[0].port

    def get_mem_ports(self) -> Sequence[Tuple[AddrRange, Port]]:
        original_mem_ports = self.mem_system.get_mem_ports()
        assert len(original_mem_ports) == 1
        original_range, _ = original_mem_ports[0]
        return [(original_range, self.tracer.cpu_side)]

    def get_size(self) -> int:
        return self.mem_system.get_size()

    def set_memory_range(self, ranges: List[AddrRange]) -> None:
        self.mem_system.set_memory_range(ranges)

    def get_memory_controllers(self) -> List[MemCtrl]:
        return self.mem_system.get_memory_controllers()

    def get_mem_interfaces(self) -> List[MemInterface]:
        return self.mem_system.get_mem_interfaces()

    def get_uninterleaved_range(self) -> List[AddrRange]:
        return self.mem_system.get_uninterleaved_range()


# The order of instantiation can be important.
processor = SimpleSwitchableProcessor(
    starting_core_type=CPUTypes.KVM,
    switch_core_type=CPUTypes.TIMING,
    isa=ISA.X86,
    num_cores=1,
)
for proc in processor.start:
    proc.core.usePerf = False

cache_hierarchy = MESITwoLevelCacheHierarchy(
    l1d_size="32KiB",
    l1d_assoc=8,
    l1i_size="32KiB",
    l1i_assoc=8,
    l2_size="256kB",
    l2_assoc=16,
    num_l2_banks=1,
)

memory = TracedMemorySystem("2GiB")

board = X86Board(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)


# The command to run after the system has booted and switched to Timing CPU.
workload_command = "sleep 1;"

# Set the workload using the systemd-based Ubuntu image.
board.set_kernel_disk_workload(
    kernel=obtain_resource("x86-linux-kernel-6.8.0-52-generic"),
    disk_image=obtain_resource("x86-ubuntu-24.04-img"),
    readfile_contents=workload_command,
)


def exit_event_handler():
    # First m5 exit (from kernel boot)
    print("First exit: kernel booted")
    yield False

    # Second m5 exit (from after_boot.sh starting)
    print("Second exit: Started `after_boot.sh` script")
    print("Switching to Timing CPU")
    processor.switch()

    # start tracing
    print("Starting trace collection.")
    memory.tracer.startTrace()

    yield False

    # Third m5 exit (from after_boot.sh finishing)
    print("Third exit: Finished `after_boot.sh` script")

    # Now, stop tracing after our workload_command runs
    print("Stopping trace collection.")
    memory.tracer.stopTrace()

    yield True


simulator = Simulator(
    board=board,
    on_exit_event={ExitEvent.EXIT: exit_event_handler()},
)

simulator.run()
