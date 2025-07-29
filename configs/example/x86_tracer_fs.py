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
from gem5.components.cachehierarchies.ruby.mesi_three_level_cache_hierarchy import (
    MESIThreeLevelCacheHierarchy,
)
from gem5.components.memory.abstract_memory_system import AbstractMemorySystem
from gem5.components.memory.multi_channel import DualChannelDDR4_2666
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
    coherence_protocol_required=CoherenceProtocol.MESI_THREE_LEVEL,
    kvm_required=True,
)


class TracedMemorySystem(AbstractMemorySystem):
    def __init__(self, size: str):
        super().__init__()
        self.mem_system = DualChannelDDR4_2666(size=size)
        # Get the number of memory channels
        num_channels = len(self.mem_system.get_memory_controllers())
        self.tracer = MemTracer(trace_file="fs_mem_trace.bin")
        # The port connection counts will be automatically determined by gem5
        # based on how many ports are connected in the get_mem_ports method

    def get_mem_ports(self) -> Sequence[Tuple[AddrRange, Port]]:
        """
        Returns the tracer's CPU-side ports. The board will connect to these.
        """
        mem_ports = self.mem_system.get_mem_ports()
        # Create a list of tracer ports by accessing them by index
        # This will cause the ports to be dynamically created as needed
        tracer_ports = [self.tracer.cpu_side[i] for i in range(len(mem_ports))]
        return [
            (mem_ports[i][0], tracer_ports[i]) for i in range(len(mem_ports))
        ]

    def incorporate_memory(self, board: AbstractBoard) -> None:
        """
        Connects the tracer's memory-side ports to the actual memory
        controllers.
        """
        self.mem_system.incorporate_memory(board)
        for i, c in enumerate(self.mem_system.get_memory_controllers()):
            self.tracer.mem_side[i] = c.port

    # The rest of the methods are simple pass-throughs to the real memory system.
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
    num_cores=40,
)
for proc in processor.start:
    proc.core.usePerf = False

cache_hierarchy = MESIThreeLevelCacheHierarchy(
    l1d_size="48KiB",
    l1d_assoc=12,
    l1i_size="32KiB",
    l1i_assoc=8,
    l2_size="2MiB",
    l2_assoc=16,
    l3_size="105MiB",
    l3_assoc=15,
    num_l3_banks=40,
)

memory = TracedMemorySystem("3GiB")

board = X86Board(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)


# The command to run after the system has booted and switched to Timing CPU.
# workload_command = "m5 exit; sleep 1; m5 exit;"
workload_command = (
    "m5 exit; dd if=/dev/zero of=/dev/null bs=1M count=1024; m5 exit;"
)

# Set the workload using the systemd-based Ubuntu image.
default_args = board.get_default_kernel_args()
custom_args = [
    arg if not arg.startswith("root=") else "root=/dev/sda2"
    for arg in default_args
]
board.set_kernel_disk_workload(
    kernel=obtain_resource("x86-linux-kernel-6.8.0-52-generic"),
    disk_image=obtain_resource("x86-ubuntu-24.04-img"),
    readfile_contents=workload_command,
    kernel_args=custom_args,
)


def exit_event_handler():
    # m5 exit (from after_boot.sh starting)
    print("First exit: Started `after_boot.sh` script")
    print("Switching to Timing CPU")
    processor.switch()

    # start tracing
    print("Starting trace collection.")
    memory.tracer.startTrace()

    yield False

    # m5 exit (from after_boot.sh finishing)
    print("Second exit: Finished `after_boot.sh` script")

    # Now, stop tracing after our workload_command runs
    print("Stopping trace collection.")
    memory.tracer.stopTrace()

    yield True


simulator = Simulator(
    board=board,
    on_exit_event={ExitEvent.EXIT: exit_event_handler()},
)

simulator.run()
