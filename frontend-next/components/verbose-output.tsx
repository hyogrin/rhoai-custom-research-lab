"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

export type VerboseEvent = {
  id: string;
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
};

type VerboseOutputProps = {
  events: VerboseEvent[];
  visible: boolean;
};

export function VerboseOutput({ events, visible }: VerboseOutputProps) {
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set());

  if (!visible || events.length === 0) return null;

  const toggle = (id: string) => {
    const next = new Set(expandedEvents);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpandedEvents(next);
  };

  return (
    <div className="mx-auto mb-4 w-full max-w-2xl">
      <div className="rounded-lg border border-border bg-card/50 p-3">
        <h4 className="mb-2 text-xs font-medium text-muted-foreground">
          Verbose Output ({events.length} events)
        </h4>
        <div className="max-h-64 space-y-0.5 overflow-y-auto font-mono text-[11px]">
          {events.map((event) => {
            const isExpanded = expandedEvents.has(event.id);
            return (
              <div key={event.id}>
                <button
                  onClick={() => toggle(event.id)}
                  className="flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left hover:bg-accent"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                  )}
                  <span className="text-primary">{event.type}</span>
                  <span className="ml-auto text-muted-foreground">
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </span>
                </button>
                {isExpanded && (
                  <pre className="ml-5 overflow-x-auto whitespace-pre-wrap rounded bg-muted/50 p-2 text-muted-foreground">
                    {JSON.stringify(event.data, null, 2)}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
