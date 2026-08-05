"use client";

import { createContext, useContext, useState, useCallback, type FC, type ReactNode } from "react";

export type CitationSource = {
  index: number;
  name: string;
  snippet: string;
  url: string;
  domain: string;
};

type CitationContextType = {
  sources: Record<number, CitationSource>;
  setSources: (sources: CitationSource[]) => void;
  clearSources: () => void;
};

const CitationContext = createContext<CitationContextType>({
  sources: {},
  setSources: () => {},
  clearSources: () => {},
});

export function useCitations() {
  return useContext(CitationContext);
}

export const CitationProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [sources, setSourcesMap] = useState<Record<number, CitationSource>>({});

  const setSources = useCallback((list: CitationSource[]) => {
    const map: Record<number, CitationSource> = {};
    for (const s of list) {
      map[s.index] = s;
    }
    setSourcesMap(map);
  }, []);

  const clearSources = useCallback(() => {
    setSourcesMap({});
  }, []);

  return (
    <CitationContext.Provider value={{ sources, setSources, clearSources }}>
      {children}
    </CitationContext.Provider>
  );
};
