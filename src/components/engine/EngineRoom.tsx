import React from 'react';
import { useEngineRoom } from '../../hooks/useEngineRoom';
import { SystemStatusHeader } from './SystemStatusHeader';
import { WorkerGrid } from './WorkerGrid';
import { JobBoard } from './JobBoard';
import { EventStream } from './EventStream';
import { JobCreator } from './JobCreator';

/**
 * EngineRoom — the canonical machine visualization.
 *
 * Every value here is read from the durable execution engine via /v1/engine/*.
 * The UI is a projection of persisted state, not a mock. On refresh it
 * reconstructs the exact same view. When there are no active jobs the system
 * shows SYSTEM IDLE / READY — nothing is animated to appear busy.
 */
export const EngineRoom: React.FC = () => {
  const engine = useEngineRoom();

  return (
    <div className="p-6 flex flex-col gap-5 h-full overflow-y-auto">
      <SystemStatusHeader engine={engine} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-1 flex flex-col gap-5">
          <JobCreator engine={engine} />
          <WorkerGrid engine={engine} />
        </div>

        <div className="lg:col-span-2 flex flex-col gap-5 min-h-0">
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold text-slate-200">
              Production Jobs
              <span className="text-[10px] font-mono text-slate-500 ml-2">live state from durable store</span>
            </h3>
            <JobBoard
              jobs={engine.jobs}
              onRetry={(id) => void engine.retryJob(id)}
              onCancel={(id) => void engine.cancelJob(id)}
            />
          </div>
          <div className="flex-1 min-h-[280px]">
            <EventStream events={engine.events} />
          </div>
        </div>
      </div>
    </div>
  );
};
