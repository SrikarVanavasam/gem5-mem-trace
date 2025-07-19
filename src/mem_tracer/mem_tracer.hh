#ifndef __MEM_TRACER_HH__
#define __MEM_TRACER_HH__

#include <fstream>

#include "mem/qport.hh"
#include "params/MemTracer.hh"
#include "sim/clocked_object.hh"

namespace gem5 {

struct TraceFileHeader
{
    uint32_t magic;
    uint32_t version;
    uint64_t buffer_size;
    uint64_t written_traces;
    uint64_t dropped_traces;
};

struct TraceRecord
{
    uint64_t low;  // address and flags.
    uint64_t high; // timestamp.
};

const int IS_VALID_SHIFT = 63;
const int IS_WRITE_SHIFT = 62;
const uint64_t ADDR_MASK = 0x000fffffffffffff; // Lower 52 bits for address.

class MemTracer : public ClockedObject
{

  public:
    MemTracer(const MemTracerParams& params);
    ~MemTracer();

    void
    init() override;

  protected: // Port interface
    Port&
    getPort(const std::string& if_name, PortID idx = InvalidPortID) override;

    class MemSidePort : public QueuedRequestPort
    {
      public:
        MemSidePort(const std::string& _name, MemTracer& _parent);

      protected:
        bool
        recvTimingResp(PacketPtr pkt) override;

        void
        recvFunctionalSnoop(PacketPtr pkt) override;

        Tick
        recvAtomicSnoop(PacketPtr pkt) override;

        void
        recvTimingSnoopReq(PacketPtr pkt) override;

        void
        recvRangeChange() override
        {
            parent.cpu_side_port.sendRangeChange();
        }

        bool
        isSnooping() const override
        {
            return parent.cpu_side_port.isSnooping();
        }

      private:
        MemTracer& parent;
    };

    class CPUSidePort : public QueuedResponsePort
    {
      public:
        CPUSidePort(const std::string& _name, MemTracer& _parent);

      protected:
        Tick
        recvAtomic(PacketPtr pkt) override;
        bool
        recvTimingReq(PacketPtr pkt) override;
        void
        recvFunctional(PacketPtr pkt) override;
        bool
        recvTimingSnoopResp(PacketPtr pkt) override;

        AddrRangeList
        getAddrRanges() const override
        {
            return parent.mem_side_port.getAddrRanges();
        }

        bool
        tryTiming(PacketPtr pkt) override
        {
            return true;
        }

      private:
        MemTracer& parent;
    };

    bool
    trySatisfyFunctional(PacketPtr pkt);

    MemSidePort mem_side_port;
    CPUSidePort cpu_side_port;

    ReqPacketQueue reqQueue;
    RespPacketQueue respQueue;
    SnoopRespPacketQueue snoopRespQueue;

    std::fstream trace_file;
    std::string trace_path;
    uint64_t records_written;

    bool tracing_enabled;

  public:
    void
    recordPacket(PacketPtr pkt);
    void
    startTrace();
    void
    stopTrace();
};

} // namespace gem5

#endif // __MEM_TRACER_HH__
