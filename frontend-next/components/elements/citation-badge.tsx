"use client";

import { type FC } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useCitations } from "@/contexts/citation-context";
import { ExternalLink } from "lucide-react";

interface CitationBadgeProps {
  index: number;
}

export const CitationBadge: FC<CitationBadgeProps> = ({ index }) => {
  const { sources } = useCitations();
  const source = sources[index];

  if (!source) {
    return (
      <span className="citation-badge citation-badge--unknown">{index}</span>
    );
  }

  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button type="button" className="citation-badge">
            {index}
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side="top"
            sideOffset={6}
            className="citation-preview"
          >
            {source.domain && (
              <div className="citation-preview__domain">
                <span className="citation-preview__domain-icon">
                  {source.domain[0]?.toUpperCase()}
                </span>
                <span className="citation-preview__domain-text">
                  {source.domain}
                </span>
              </div>
            )}
            <p className="citation-preview__title">{source.name}</p>
            {source.snippet && (
              <p className="citation-preview__snippet">{source.snippet}</p>
            )}
            {source.url && (
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="citation-preview__link"
              >
                <ExternalLink className="size-3" />
                <span>Open source</span>
              </a>
            )}
            <Tooltip.Arrow className="fill-[var(--color-popover)]" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
};
