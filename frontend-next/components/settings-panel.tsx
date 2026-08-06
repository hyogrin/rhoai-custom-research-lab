"use client";

import { useState } from "react";
import { X, Target, Repeat, Globe, Map, ShieldCheck, Layers, FileText, Trash2 } from "lucide-react";
import { useSettings, useDocuments } from "@/app/providers";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type SettingsPanelProps = {
  open: boolean;
  onClose: () => void;
};

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const { settings, setSettings } = useSettings();
  const { documents, refreshDocuments } = useDocuments();
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
      />
      {/* Panel */}
      <div className="fixed inset-y-0 right-0 z-50 w-80 border-l border-border bg-card shadow-xl">
        <div className="flex h-14 items-center justify-between border-b border-border px-4">
          <h2 className="text-sm font-semibold">Research Settings</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent"
            aria-label="Close settings"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col gap-6 overflow-y-auto p-4">
          {/* Sliders */}
          <SliderSetting
            icon={<Target className="h-4 w-4 text-primary" />}
            label="Quality Threshold"
            description="Minimum quality score (1-10) before stopping"
            value={settings.qualityThreshold}
            min={1}
            max={10}
            step={0.5}
            onChange={(v) => setSettings({ ...settings, qualityThreshold: v })}
          />
          <SliderSetting
            icon={<Repeat className="h-4 w-4 text-primary" />}
            label="Max Iterations"
            description="Maximum harness iterations"
            value={settings.maxIterations}
            min={1}
            max={10}
            step={1}
            onChange={(v) => setSettings({ ...settings, maxIterations: v })}
          />

          <div className="border-t border-border" />

          {/* Toggles */}
          <ToggleSetting
            icon={<Globe className="h-4 w-4 text-blue-400" />}
            label="Web Search"
            description="Search the web for up-to-date information"
            checked={settings.enableWebSearch}
            onChange={(v) => setSettings({ ...settings, enableWebSearch: v })}
          />
          <ToggleSetting
            icon={<Map className="h-4 w-4 text-green-400" />}
            label="Research Planning"
            description="Generate structured plan before executing"
            checked={settings.enablePlanning}
            onChange={(v) => setSettings({ ...settings, enablePlanning: v })}
          />
          <ToggleSetting
            icon={<ShieldCheck className="h-4 w-4 text-amber-400" />}
            label="Fact Check"
            description="Cross-reference claims against sources"
            checked={settings.enableFactCheck}
            onChange={(v) => setSettings({ ...settings, enableFactCheck: v })}
          />
          <ToggleSetting
            icon={<Layers className="h-4 w-4 text-purple-400" />}
            label="Parallel Processing"
            description="Run searches and verifications concurrently"
            checked={settings.enableParallel}
            onChange={(v) => setSettings({ ...settings, enableParallel: v })}
          />
          <ToggleSetting
            icon={<FileText className="h-4 w-4 text-cyan-400" />}
            label="Sectioned Report"
            description="Decompose into sub-topics with independent sections"
            checked={settings.enableSectioned}
            onChange={(v) => setSettings({ ...settings, enableSectioned: v })}
          />

          <div className="border-t border-border" />

          {/* Document Database Reset */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Trash2 className="h-4 w-4 text-red-400" />
              <div className="flex-1">
                <span className="text-sm font-medium">Reset Document Database</span>
                <p className="text-xs text-muted-foreground">
                  Delete all uploaded documents, chunks, and embeddings
                  {documents.length > 0 && (
                    <span className="ml-1 text-red-400">({documents.length} document{documents.length > 1 ? "s" : ""})</span>
                  )}
                </p>
              </div>
            </div>

            {!confirmReset ? (
              <button
                type="button"
                onClick={() => setConfirmReset(true)}
                disabled={documents.length === 0}
                className="w-full rounded-md border border-red-300/30 px-3 py-1.5 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Reset Documents
              </button>
            ) : (
              <div className="space-y-2 rounded-md border border-red-400/30 bg-red-500/5 p-3">
                <p className="text-xs text-red-400 font-medium">
                  This will permanently delete all {documents.length} document{documents.length > 1 ? "s" : ""} and their embeddings. This cannot be undone.
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmReset(false)}
                    className="flex-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={resetting}
                    onClick={async () => {
                      setResetting(true);
                      try {
                        const res = await fetch(`${API_URL}/documents/reset`, { method: "DELETE" });
                        if (res.ok) {
                          await refreshDocuments();
                          setConfirmReset(false);
                        }
                      } catch { /* ignore */ }
                      setResetting(false);
                    }}
                    className="flex-1 rounded-md bg-red-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50"
                  >
                    {resetting ? "Deleting..." : "Confirm Delete"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function SliderSetting({
  icon,
  label,
  description,
  value,
  min,
  max,
  step,
  onChange,
}: {
  icon: React.ReactNode;
  label: string;
  description: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {icon}
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{label}</span>
            <span className="text-xs font-mono text-muted-foreground">
              {value}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-primary"
      />
    </div>
  );
}

function ToggleSetting({
  icon,
  label,
  description,
  checked,
  onChange,
}: {
  icon: React.ReactNode;
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <div className="mt-0.5">{icon}</div>
      <div className="flex-1">
        <span className="text-sm font-medium">{label}</span>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? "bg-primary" : "bg-muted-foreground/30"
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-4" : "translate-x-0"
          }`}
        />
      </button>
    </label>
  );
}
