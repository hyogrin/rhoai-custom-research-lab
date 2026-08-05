"use client";

import { useState } from "react";
import { Thread } from "@/components/thread";
import { ThreadShell } from "@/components/thread-shell";
import { SettingsPanel } from "@/components/settings-panel";

export default function Home() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <>
      <ThreadShell
        collapsed={sidebarCollapsed}
        onCollapsedChange={setSidebarCollapsed}
        mobileSidebarOpen={mobileSidebarOpen}
        onMobileSidebarOpenChange={setMobileSidebarOpen}
      >
        <div className="bg-muted/30 flex h-full flex-col overflow-hidden p-2 md:pl-0">
          <div className="bg-background flex flex-1 flex-col overflow-hidden rounded-lg">
            <Header
              sidebarCollapsed={sidebarCollapsed}
              onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
              onOpenMobileSidebar={() => setMobileSidebarOpen(true)}
              onOpenSettings={() => setSettingsOpen(true)}
            />
            <main className="flex-1 overflow-hidden">
              <Thread />
            </main>
          </div>
        </div>
      </ThreadShell>
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}

import { useSettings } from "@/app/providers";
import {
  PanelLeftIcon,
  MenuIcon,
  Settings,
  Languages,
  Eye,
  EyeOff,
  List,
  ListX,
} from "lucide-react";

function Header({
  sidebarCollapsed,
  onToggleSidebar,
  onOpenMobileSidebar,
  onOpenSettings,
}: {
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onOpenMobileSidebar: () => void;
  onOpenSettings: () => void;
}) {
  const { settings, setSettings } = useSettings();

  const toggleLanguage = () => {
    setSettings({
      ...settings,
      language: settings.language === "en-US" ? "ko-KR" : "en-US",
    });
  };

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 px-4">
      <button
        onClick={onOpenMobileSidebar}
        className="inline-flex size-8 items-center justify-center rounded-md hover:bg-muted md:hidden"
        aria-label="Open menu"
      >
        <MenuIcon className="size-4" />
      </button>
      <button
        onClick={onToggleSidebar}
        className="hidden size-8 items-center justify-center rounded-md hover:bg-muted md:inline-flex"
        aria-label={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
      >
        <PanelLeftIcon className="size-4" />
      </button>
      <span className="min-w-0 truncate text-sm font-medium">
        Deep Research Lab
      </span>

      <div className="ml-auto flex items-center gap-1">
        <button
          onClick={() => setSettings({ ...settings, verbose: !settings.verbose })}
          className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
            settings.verbose
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-muted"
          }`}
          aria-label="Toggle verbose"
        >
          {settings.verbose ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
          <span className="hidden sm:inline">Verbose</span>
        </button>
        <button
          onClick={() => setSettings({ ...settings, logSse: !settings.logSse })}
          className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
            settings.logSse
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-muted"
          }`}
          aria-label="Toggle step history"
        >
          {settings.logSse ? <List className="size-3.5" /> : <ListX className="size-3.5" />}
          <span className="hidden sm:inline">Steps</span>
        </button>
        <button
          onClick={toggleLanguage}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
          aria-label="Toggle language"
        >
          <Languages className="size-3.5" />
          <span>{settings.language === "en-US" ? "EN" : "KR"}</span>
        </button>
        <button
          onClick={onOpenSettings}
          className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
          aria-label="Settings"
        >
          <Settings className="size-4" />
        </button>
      </div>
    </header>
  );
}
