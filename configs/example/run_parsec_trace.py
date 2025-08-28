import argparse
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
    SimpleMemDelay,
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
from gem5.resources.resource import (
    DiskImageResource,
    KernelResource,
)
from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires

# Parse arguments first
parser = argparse.ArgumentParser()
parser.add_argument("benchmark", help="The PARSEC benchmark to run.")
parser.add_argument("trace_file", help="The output file for the memory trace.")
args = parser.parse_args()

requires(
    isa_required=ISA.X86,
    coherence_protocol_required=CoherenceProtocol.MESI_THREE_LEVEL,
    kvm_required=True,
)


class TracedMemorySystem(AbstractMemorySystem):
    def __init__(self, size: str):
        super().__init__()
        self.mem_system = DualChannelDDR4_2666(size=size)
        self.tracer = MemTracer(trace_file="fs_mem_trace.bin")
        # Pre-create delay objects (will be configured in incorporate_memory)
        # This ensures they're part of the object hierarchy and not orphaned
        num_channels = len(self.mem_system.get_memory_controllers())
        self.delays = [SimpleMemDelay() for _ in range(num_channels)]

    def get_mem_ports(self) -> Sequence[Tuple[AddrRange, Port]]:
        """
        Returns the delay objects' CPU-side ports. The board will connect to these.
        This creates the flow: CPU -> delay -> tracer -> memory controller
        """
        mem_ports = self.mem_system.get_mem_ports()
        # Connect: delay -> tracer -> memory controller
        # Return the delay objects' ports for the CPU to connect to
        delay_ports = []
        for i in range(len(mem_ports)):
            delay = self.delays[i]
            # Configure the delay with 380ns latency
            delay.read_req = "380ns"
            delay.read_resp = "380ns"
            delay.write_req = "380ns"
            delay.write_resp = "380ns"

            # Connect: delay -> tracer -> memory controller
            delay.mem_side_port = self.tracer.cpu_side[i]
            delay_ports.append(delay.cpu_side_port)
        return [
            (mem_ports[i][0], delay_ports[i]) for i in range(len(mem_ports))
        ]

    def incorporate_memory(self, board: AbstractBoard) -> None:
        """
        Connects the tracer's memory-side ports to the actual memory controllers.
        """
        self.mem_system.incorporate_memory(board)
        for i, c in enumerate(self.mem_system.get_memory_controllers()):
            # Connect tracer's mem_side to actual memory controllers
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


NUM_CORES = 8
NUM_L3_BANKS = 48

# NUM_CORES = 1
# NUM_L3_BANKS = 1

processor = SimpleSwitchableProcessor(
    starting_core_type=CPUTypes.KVM,
    switch_core_type=CPUTypes.TIMING,
    isa=ISA.X86,
    num_cores=NUM_CORES,
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
    l3_size="300MiB",
    l3_assoc=20,
    num_l3_banks=NUM_L3_BANKS,
)

memory = TracedMemorySystem("3GiB")
# Update the tracer to use the specified trace file
memory.tracer.trace_file = args.trace_file

board = X86Board(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)


# The command to run after the system has booted and switched to Timing CPU.
workload_command = f"m5 exit; /home/gem5/parsec-benchmark/bin/parsecmgmt -a run -p {args.benchmark} -i simsmall -n 8; m5 exit;"

# Set the workload using the systemd-based Ubuntu image.
default_args = board.get_default_kernel_args()
custom_args = [
    arg if not arg.startswith("root=") else "root=/dev/sda2"
    for arg in default_args
]
board.set_kernel_disk_workload(
    # kernel=obtain_resource("x86-linux-kernel-6.8.0-52-generic"),
    kernel=KernelResource(
        "/fast-lab-share/srikarv2/gem5-mem-trace/vmlinux-x86-6.8.0-71-generic"
    ),
    disk_image=DiskImageResource(
        "/fast-lab-share/srikarv2/gem5-mem-trace/x86-ubuntu-24.04-parsec-img"
    ),
    readfile_contents=workload_command,
    kernel_args=custom_args,
)


def exit_event_handler():
    # m5 exit (from after_boot.sh starting)
    print("Switching to Timing CPU")
    processor.switch()

    # start tracing
    print("Starting trace collection.")
    memory.tracer.startTrace()

    yield False

    # Now, stop tracing after our workload_command runs
    print("Stopping trace collection.")
    memory.tracer.stopTrace()

    yield True


simulator = Simulator(
    board=board,
    on_exit_event={ExitEvent.EXIT: exit_event_handler()},
)

simulator.run()
