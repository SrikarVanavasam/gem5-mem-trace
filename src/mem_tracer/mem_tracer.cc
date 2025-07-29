#include "mem_tracer/mem_tracer.hh"

#include "base/trace.hh"
#include "debug/MemTracer.hh"
#include "mem/packet.hh"
#include "mem/packet_access.hh"

namespace gem5 {

MemTracer::MemTracer(const MemTracerParams& p)
    : ClockedObject(p), trace_path(p.trace_file), records_written(0),
      tracing_enabled(false)
{
    // The ports will be created dynamically when getPort is called
    // with specific port names and indices. For now, we just initialize
    // empty vectors that will be populated as needed.

    trace_file.open(trace_path, std::ios::out | std::ios::in |
                                    std::ios::binary | std::ios::trunc);
    if (!trace_file.is_open()) {
        fatal("MemTracer: Unable to open trace file '%s'\n", trace_path);
    }

    TraceFileHeader header;
    header.magic = 0x54524143; // "TRAC"
    header.version = 1;
    header.buffer_size = 0;
    header.written_traces = 0;
    header.dropped_traces = 0;
    trace_file.write(reinterpret_cast<char*>(&header), sizeof(header));
}

MemTracer::~MemTracer()
{
    if (trace_file.is_open()) {
        trace_file.seekp(0, std::ios::beg);

        TraceFileHeader header;
        header.magic = 0x54524143;
        header.version = 1;
        header.buffer_size = 0;
        header.written_traces = records_written;
        header.dropped_traces = 0;
        trace_file.write(reinterpret_cast<char*>(&header), sizeof(header));

        trace_file.close();
    }

    // Clean up dynamically created ports
    for (auto port : mem_side_ports) { delete port; }
    for (auto port : cpu_side_ports) { delete port; }
}

void
MemTracer::init()
{
    // Only check ports that have been created
    for (auto port : cpu_side_ports) {
        if (!port->isConnected())
            fatal("Memory tracer is not connected on cpu side.\n");
    }

    for (auto port : mem_side_ports) {
        if (!port->isConnected())
            fatal("Memory tracer is not connected on mem side.\n");
    }
}

Port&
MemTracer::getPort(const std::string& if_name, PortID idx)
{
    if (if_name == "mem_side") {
        // Ensure we have enough ports
        while (mem_side_ports.size() <= (size_t)idx) {
            mem_side_ports.push_back(new MemSidePort(
                name() + ".mem_side" + std::to_string(mem_side_ports.size()),
                *this, mem_side_ports.size()));
        }
        return *mem_side_ports[idx];
    } else if (if_name == "cpu_side") {
        // Ensure we have enough ports
        while (cpu_side_ports.size() <= (size_t)idx) {
            cpu_side_ports.push_back(new CPUSidePort(
                name() + ".cpu_side" + std::to_string(cpu_side_ports.size()),
                *this, cpu_side_ports.size()));
        }
        return *cpu_side_ports[idx];
    } else {
        return ClockedObject::getPort(if_name, idx);
    }
}

bool
MemTracer::trySatisfyFunctional(PacketPtr pkt)
{
    // Try to satisfy the functional request on any port
    for (auto& port : cpu_side_ports) {
        if (port->trySatisfyFunctional(pkt)) {
            return true;
        }
    }
    for (auto& port : mem_side_ports) {
        if (port->trySatisfyFunctional(pkt)) {
            return true;
        }
    }
    return false;
}

void
MemTracer::startTrace()
{
    DPRINTF(MemTracer, "Trace collection started.\n");
    tracing_enabled = true;
}

void
MemTracer::stopTrace()
{
    DPRINTF(MemTracer, "Trace collection stopped.\n");
    tracing_enabled = false;
}

void
MemTracer::recordPacket(PacketPtr pkt)
{
    if (!tracing_enabled || (!pkt->isRead() && !pkt->isWrite())) { return; }

    TraceRecord record;
    uint64_t packed_data = 0;

    packed_data |= (1ULL << IS_VALID_SHIFT);
    if (pkt->isWrite() || pkt->isWriteback()) {
        packed_data |= (1ULL << IS_WRITE_SHIFT);
    }
    uint64_t address = pkt->getAddr() & ADDR_MASK;
    packed_data |= address;

    record.low = packed_data;
    record.high = curTick();

    trace_file.write(reinterpret_cast<char*>(&record), sizeof(TraceRecord));
    records_written++;
}

MemTracer::MemSidePort::MemSidePort(const std::string& _name,
                                    MemTracer& _parent, PortID _id)
    : QueuedRequestPort(_name, reqQueue, snoopRespQueue),
      reqQueue(_parent, *this, _name + ".reqQueue"),
      snoopRespQueue(_parent, *this, false, _name + ".snoopRespQueue"),
      parent(_parent), id(_id)
{
}

bool
MemTracer::MemSidePort::recvTimingResp(PacketPtr pkt)
{
    const Tick when = curTick();
    parent.cpu_side_ports[id]->schedTimingResp(pkt, when);
    return true;
}

void
MemTracer::MemSidePort::recvFunctionalSnoop(PacketPtr pkt)
{
    if (parent.trySatisfyFunctional(pkt)) {
        pkt->makeResponse();
    } else {
        parent.cpu_side_ports[id]->sendFunctionalSnoop(pkt);
    }
}

Tick
MemTracer::MemSidePort::recvAtomicSnoop(PacketPtr pkt)
{
    return parent.cpu_side_ports[id]->sendAtomicSnoop(pkt);
}

void
MemTracer::MemSidePort::recvTimingSnoopReq(PacketPtr pkt)
{
    parent.cpu_side_ports[id]->sendTimingSnoopReq(pkt);
}

MemTracer::CPUSidePort::CPUSidePort(const std::string& _name,
                                    MemTracer& _parent, PortID _id)
    : QueuedResponsePort(_name, respQueue),
      respQueue(_parent, *this, false, _name + ".respQueue"),
      parent(_parent), id(_id)
{
}

Tick
MemTracer::CPUSidePort::recvAtomic(PacketPtr pkt)
{
    // No delay, just forward
    return parent.mem_side_ports[id]->sendAtomic(pkt);
}

bool
MemTracer::CPUSidePort::recvTimingReq(PacketPtr pkt)
{
    parent.recordPacket(pkt);
    const Tick when = curTick();
    parent.mem_side_ports[id]->schedTimingReq(pkt, when);
    return true;
}

void
MemTracer::CPUSidePort::recvFunctional(PacketPtr pkt)
{
    if (parent.trySatisfyFunctional(pkt)) {
        pkt->makeResponse();
    } else {
        parent.mem_side_ports[id]->sendFunctional(pkt);
    }
}

bool
MemTracer::CPUSidePort::recvTimingSnoopResp(PacketPtr pkt)
{
    const Tick when = curTick();
    parent.mem_side_ports[id]->schedTimingSnoopResp(pkt, when);
    return true;
}

} // namespace gem5
