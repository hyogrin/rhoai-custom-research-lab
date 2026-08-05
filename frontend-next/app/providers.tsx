"use client";

import {
  useMemo,
  useState,
  useRef,
  useCallback,
  useEffect,
  createContext,
  useContext,
} from "react";
import {
  AssistantRuntimeProvider,
  ExportedMessageRepository,
  fromThreadMessageLike,
  generateId,
} from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { fromAgUiMessages } from "@assistant-ui/react-ag-ui";
import type { UseAgUiThreadListAdapter } from "@assistant-ui/react-ag-ui";
import type { ThreadHistoryAdapter, ThreadMessage } from "@assistant-ui/react";
import { HttpAgent } from "@ag-ui/client";
import { CitationProvider } from "@/contexts/citation-context";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const THREAD_STORAGE_KEY = "research-active-thread-id";

const FALLBACK_STATUS = {
  type: "complete" as const,
  reason: "unknown" as const,
};

export type ResearchSettings = {
  qualityThreshold: number;
  maxIterations: number;
  enableWebSearch: boolean;
  enablePlanning: boolean;
  enableFactCheck: boolean;
  enableParallel: boolean;
  enableSectioned: boolean;
  verbose: boolean;
  logSse: boolean;
  language: "en-US" | "ko-KR";
};

const defaultSettings: ResearchSettings = {
  qualityThreshold: 7.0,
  maxIterations: 2,
  enableWebSearch: true,
  enablePlanning: true,
  enableFactCheck: true,
  enableParallel: true,
  enableSectioned: true,
  verbose: false,
  logSse: false,
  language: "en-US",
};

export type ThreadInfo = {
  status: "regular";
  id: string;
  title?: string;
};

export type DocumentInfo = {
  id: string;
  name: string;
  file_type: string | null;
  chunk_count: number;
  status: string;
  created_at: string;
};

type SettingsContextType = {
  settings: ResearchSettings;
  setSettings: (s: ResearchSettings) => void;
};

type ThreadContextType = {
  threads: ThreadInfo[];
  activeThreadId: string | null;
  switchToThread: (id: string) => void;
  switchToNewThread: () => void;
  deleteThread: (id: string) => Promise<void>;
  refreshThreads: () => Promise<void>;
};

type DocumentContextType = {
  documents: DocumentInfo[];
  refreshDocuments: () => Promise<void>;
};

export const SettingsContext = createContext<SettingsContextType>({
  settings: defaultSettings,
  setSettings: () => {},
});

export const ThreadContext = createContext<ThreadContextType>({
  threads: [],
  activeThreadId: null,
  switchToThread: () => {},
  switchToNewThread: () => {},
  deleteThread: async () => {},
  refreshThreads: async () => {},
});

export const DocumentContext = createContext<DocumentContextType>({
  documents: [],
  refreshDocuments: async () => {},
});

export function useSettings() {
  return useContext(SettingsContext);
}

export function useThreads() {
  return useContext(ThreadContext);
}

export function useDocuments() {
  return useContext(DocumentContext);
}

async function fetchThreadMessages(
  threadId: string,
): Promise<ThreadMessage[]> {
  try {
    const res = await fetch(`${API_URL}/threads/${threadId}/messages`);
    if (!res.ok) return [];
    const data = await res.json();
    const raw = data.messages || [];
    if (raw.length === 0) return [];

    const likeMsgs = fromAgUiMessages(raw);
    return likeMsgs.map((m) =>
      fromThreadMessageLike(m, generateId(), FALLBACK_STATUS),
    );
  } catch {
    return [];
  }
}

function getStoredThreadId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(THREAD_STORAGE_KEY);
}

function storeThreadId(id: string | null) {
  if (typeof window === "undefined") return;
  if (id) {
    localStorage.setItem(THREAD_STORAGE_KEY, id);
  } else {
    localStorage.removeItem(THREAD_STORAGE_KEY);
  }
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<ResearchSettings>(defaultSettings);
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(() =>
    getStoredThreadId(),
  );
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);

  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  const activeThreadIdRef = useRef(activeThreadId);
  activeThreadIdRef.current = activeThreadId;

  useEffect(() => {
    storeThreadId(activeThreadId);
  }, [activeThreadId]);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/documents`);
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const fetchThreads = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/threads`);
      if (res.ok) {
        const data = await res.json();
        const list: ThreadInfo[] = (data.threads || []).map(
          (t: { id: string; title?: string }) => ({
            status: "regular" as const,
            id: t.id,
            title: t.title || "New conversation",
          }),
        );
        setThreads(list);
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    fetchThreads();
  }, [fetchThreads]);

  const switchToNewThread = useCallback(() => {
    setActiveThreadId(null);
  }, []);

  const switchToThread = useCallback((id: string) => {
    setActiveThreadId(id);
  }, []);

  const deleteThread = useCallback(
    async (id: string) => {
      try {
        await fetch(`${API_URL}/threads/${id}`, { method: "DELETE" });
        if (activeThreadIdRef.current === id) setActiveThreadId(null);
        await fetchThreads();
      } catch {
        /* ignore */
      }
    },
    [fetchThreads],
  );

  const historyAdapter = useMemo<ThreadHistoryAdapter>(
    () => ({
      async load() {
        const threadId = activeThreadIdRef.current;
        if (!threadId) return { messages: [] };

        try {
          const res = await fetch(
            `${API_URL}/threads/${threadId}/messages`,
          );
          if (!res.ok) return { messages: [] };
          const data = await res.json();
          const raw = data.messages || [];
          if (raw.length === 0) return { messages: [] };

          return ExportedMessageRepository.fromArray(fromAgUiMessages(raw));
        } catch {
          return { messages: [] };
        }
      },
      async append() {
        // LangGraph checkpointer handles persistence on the backend
      },
    }),
    [],
  );

  const threadListAdapter = useMemo<UseAgUiThreadListAdapter>(
    () => ({
      threadId: activeThreadId ?? undefined,
      threads,
      onSwitchToNewThread: () => {
        switchToNewThread();
      },
      onSwitchToThread: async (id: string) => {
        switchToThread(id);
        const messages = await fetchThreadMessages(id);
        return { messages };
      },
      onDelete: async (id: string) => {
        await deleteThread(id);
      },
    }),
    [activeThreadId, threads, switchToNewThread, switchToThread, deleteThread],
  );

  const customFetch = useCallback(
    async (url: string, init: RequestInit): Promise<Response> => {
      if (init.body) {
        try {
          const body = JSON.parse(init.body as string);
          body.forwardedProps = {
            ...body.forwardedProps,
            settings: settingsRef.current,
          };
          init = { ...init, body: JSON.stringify(body) };
        } catch {
          // not JSON, pass through
        }
      }
      return fetch(url, init);
    },
    [],
  );

  const agent = useMemo(
    () =>
      new HttpAgent({
        url:
          process.env.NEXT_PUBLIC_AGENT_URL ?? "http://localhost:8000/agent",
        fetch: customFetch,
      }),
    [customFetch],
  );

  const runtime = useAgUiRuntime({
    agent,
    showThinking: true,
    adapters: {
      history: historyAdapter,
      threadList: threadListAdapter,
    },
  });

  const threadCtx = useMemo<ThreadContextType>(
    () => ({
      threads,
      activeThreadId,
      switchToThread,
      switchToNewThread,
      deleteThread,
      refreshThreads: fetchThreads,
    }),
    [
      threads,
      activeThreadId,
      switchToThread,
      switchToNewThread,
      deleteThread,
      fetchThreads,
    ],
  );

  const docCtx = useMemo<DocumentContextType>(
    () => ({ documents, refreshDocuments: fetchDocuments }),
    [documents, fetchDocuments],
  );

  return (
    <SettingsContext.Provider value={{ settings, setSettings }}>
      <DocumentContext.Provider value={docCtx}>
        <ThreadContext.Provider value={threadCtx}>
          <AssistantRuntimeProvider runtime={runtime}>
            <CitationProvider>
              {children}
            </CitationProvider>
          </AssistantRuntimeProvider>
        </ThreadContext.Provider>
      </DocumentContext.Provider>
    </SettingsContext.Provider>
  );
}
