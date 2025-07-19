#include "mem_tracer/mem_tracer.hh"

#include "base/trace.hh"
#include "debug/MemTracer.hh"
#include "mem/packet.hh"
#include "mem/packet_access.hh"

namespace gem5 {

MemTracer::MemTracer(const MemTracerParams& p)
    : ClockedObject(p), mem_side_port(name() + ".mem_side", *this),
      cpu_side_port(name() + ".cpu_side", *this),
      reqQueue(*this, mem_side_port), respQueue(*this, cpu_side_port),
      snoopRespQueue(*this, mem_side_port), trace_path(p.trace_file),
      records_written(0), tracing_enabled(false)
{
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
}

void
MemTracer::init()
{
    if (!cpu_side_port.isConnected() || !mem_side_port.isConnected())
        fatal("Memory tracer is not connected on both sides.\n");
}

Port&
MemTracer::getPort(const std::string& if_name, PortID idx)
{
    if (if_name == "mem_side") {
        return mem_side_port;
    } else if (if_name == "cpu_side") {
        return cpu_side_port;
    } else {
        return ClockedObject::getPort(if_name, idx);
    }
}

bool
MemTracer::trySatisfyFunctional(PacketPtr pkt)
{
    return cpu_side_port.trySatisfyFunctional(pkt) ||
           mem_side_port.trySatisfyFunctional(pkt);
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
    if (!tracing_enabled) { return; }

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
                                    MemTracer& _parent)
    : QueuedRequestPort(_name, _parent.reqQueue, _parent.snoopRespQueue),
      parent(_parent)
{
}

bool
MemTracer::MemSidePort::recvTimingResp(PacketPtr pkt)
{
    const Tick when = curTick();
    parent.cpu_side_port.schedTimingResp(pkt, when);
    return true;
}

void
MemTracer::MemSidePort::recvFunctionalSnoop(PacketPtr pkt)
{
    if (parent.trySatisfyFunctional(pkt)) {
        pkt->makeResponse();
    } else {
        parent.cpu_side_port.sendFunctionalSnoop(pkt);
    }
}

Tick
MemTracer::MemSidePort::recvAtomicSnoop(PacketPtr pkt)
{
    return parent.cpu_side_port.sendAtomicSnoop(pkt);
}

void
MemTracer::MemSidePort::recvTimingSnoopReq(PacketPtr pkt)
{
    parent.cpu_side_port.sendTimingSnoopReq(pkt);
}

MemTracer::CPUSidePort::CPUSidePort(const std::string& _name,
                                    MemTracer& _parent)
    : QueuedResponsePort(_name, _parent.respQueue), parent(_parent)
{
}

Tick
MemTracer::CPUSidePort::recvAtomic(PacketPtr pkt)
{
    // No delay, just forward
    return parent.mem_side_port.sendAtomic(pkt);
}

bool
MemTracer::CPUSidePort::recvTimingReq(PacketPtr pkt)
{
    parent.recordPacket(pkt);
    const Tick when = curTick();
    parent.mem_side_port.schedTimingReq(pkt, when);
    return true;
}

void
MemTracer::CPUSidePort::recvFunctional(PacketPtr pkt)
{
    if (parent.trySatisfyFunctional(pkt)) {
        pkt->makeResponse();
    } else {
        parent.mem_side_port.sendFunctional(pkt);
    }
}

bool
MemTracer::CPUSidePort::recvTimingSnoopResp(PacketPtr pkt)
{
    const Tick when = curTick();
    parent.mem_side_port.schedTimingSnoopResp(pkt, when);
    return true;
}

} // namespace gem5
