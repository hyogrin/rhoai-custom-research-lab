"use client";

import { cn } from "@/lib/utils";
import { useSettings, useThreads } from "@/app/providers";
import { useAui } from "@assistant-ui/react";
import {
  PanelLeftIcon,
  PlusIcon,
  MessageSquare,
  Trash2,
  X,
} from "lucide-react";
import { type FC, type ReactNode, type MouseEvent, useCallback } from "react";

type ThreadShellProps = {
  children: ReactNode;
  collapsed?: boolean;
  onCollapsedChange?: (value: boolean) => void;
  mobileSidebarOpen?: boolean;
  onMobileSidebarOpenChange?: (value: boolean) => void;
};

export const ThreadShell: FC<ThreadShellProps> = ({
  children,
  collapsed = false,
  onCollapsedChange,
  mobileSidebarOpen = false,
  onMobileSidebarOpenChange,
}) => {
  const { settings } = useSettings();
  const { threads, activeThreadId } = useThreads();
  const aui = useAui();
  const isKorean = settings.language === "ko-KR";

  const handleNewThread = useCallback(() => {
    aui.threads.switchToNewThread();
  }, [aui]);

  const handleSwitchThread = useCallback(
    (id: string) => {
      aui.threads.switchToThread(id);
    },
    [aui],
  );

  const handleDeleteThread = useCallback(
    (id: string) => {
      aui.threads.item({ id }).delete();
    },
    [aui],
  );

  const closeMobileAfterNav = (e: MouseEvent<HTMLDivElement>) => {
    if (!(e.target instanceof Element)) return;
    if (e.target.closest("[data-thread-item]")) {
      onMobileSidebarOpenChange?.(false);
    }
  };

  const sidebarContent = (
    <div className="flex flex-col gap-0.5 p-3">
      <button
        onClick={handleNewThread}
        className="flex h-8 items-center gap-2 rounded-md px-2.5 text-sm font-normal hover:bg-muted"
      >
        <PlusIcon className="size-4 shrink-0" />
        <span className={cn(collapsed && "hidden")}>
          {isKorean ? "새 대화" : "New Thread"}
        </span>
      </button>
      {threads.map((thread) => (
        <div
          key={thread.id}
          data-thread-item
          className={cn(
            "group relative flex h-8 items-center rounded-md transition-colors hover:bg-muted",
            activeThreadId === thread.id && "bg-muted",
          )}
        >
          <button
            onClick={() => handleSwitchThread(thread.id)}
            className="flex h-full min-w-0 flex-1 items-center rounded-md px-2.5 text-sm"
          >
            <MessageSquare className="size-3.5 shrink-0 mr-2 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">{thread.title}</span>
          </button>
          <button
            onClick={() => handleDeleteThread(thread.id)}
            className="absolute right-1.5 top-1/2 hidden size-6 -translate-y-1/2 items-center justify-center rounded-md text-destructive hover:bg-destructive/10 group-hover:flex"
            aria-label="Delete"
          >
            <Trash2 className="size-3.5" />
          </button>
        </div>
      ))}
      {threads.length === 0 && !collapsed && (
        <p className="px-2.5 py-4 text-xs text-muted-foreground">
          {isKorean ? "아직 대화가 없습니다" : "No conversations yet"}
        </p>
      )}
    </div>
  );

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "bg-muted/30 hidden h-full shrink-0 flex-col overflow-hidden border-r transition-[width] duration-200 md:flex",
          collapsed ? "w-12" : "w-64",
        )}
      >
        <div className="flex h-12 shrink-0 items-center px-2">
          <button
            onClick={() => onCollapsedChange?.(!collapsed)}
            className="inline-flex size-8 items-center justify-center rounded-md hover:bg-muted"
            aria-label={collapsed ? "Show sidebar" : "Hide sidebar"}
          >
            <PanelLeftIcon className="size-4" />
          </button>
          {!collapsed && (
            <span className="ml-2 truncate text-sm font-medium">
              {isKorean ? "대화 목록" : "Chats"}
            </span>
          )}
        </div>
        <div
          className={cn(
            "flex-1 overflow-y-auto transition-opacity duration-150",
            collapsed && "pointer-events-none opacity-0",
          )}
        >
          {sidebarContent}
        </div>
      </aside>

      {/* Mobile sidebar (overlay) */}
      {mobileSidebarOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/50 md:hidden"
            onClick={() => onMobileSidebarOpenChange?.(false)}
          />
          <div className="fixed inset-y-0 left-0 z-50 w-72 bg-background border-r border-border shadow-xl md:hidden flex flex-col">
            <div className="flex h-12 items-center justify-between px-4">
              <span className="text-sm font-medium">
                {isKorean ? "대화 목록" : "Chats"}
              </span>
              <button
                onClick={() => onMobileSidebarOpenChange?.(false)}
                className="inline-flex size-8 items-center justify-center rounded-md hover:bg-muted"
                aria-label="Close"
              >
                <X className="size-4" />
              </button>
            </div>
            <div
              className="flex-1 overflow-y-auto"
              onClick={closeMobileAfterNav}
            >
              {sidebarContent}
            </div>
          </div>
        </>
      )}

      {/* Main content */}
      <div className="min-w-0 flex-1 overflow-hidden">{children}</div>
    </div>
  );
};
