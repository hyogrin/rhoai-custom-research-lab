{{/*
Expand the name of the chart.
*/}}
{{- define "doc-research.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "doc-research.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "doc-research.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "doc-research.labels" -}}
helm.sh/chart: {{ include "doc-research.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/part-of: {{ include "doc-research.name" . }}
{{- end }}

{{/*
Selector labels for a named component.
Usage: {{ include "doc-research.selectorLabels" (dict "name" "backend" "root" .) }}
*/}}
{{- define "doc-research.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end }}

{{/*
Full labels for a named component (common + selector).
Usage: {{ include "doc-research.componentLabels" (dict "name" "backend" "root" .) }}
*/}}
{{- define "doc-research.componentLabels" -}}
{{ include "doc-research.labels" .root }}
{{ include "doc-research.selectorLabels" . }}
{{- end }}

{{/*
Secret name.
*/}}
{{- define "doc-research.secretName" -}}
{{- include "doc-research.fullname" . }}-secret
{{- end }}

{{/*
ConfigMap name.
*/}}
{{- define "doc-research.configMapName" -}}
{{- include "doc-research.fullname" . }}-config
{{- end }}

{{/*
Container image path.
Usage: {{ include "doc-research.image" (dict "image" "backend" "root" .) }}
*/}}
{{- define "doc-research.image" -}}
{{- printf "%s/%s:%s" .root.Values.global.registry .image .root.Values.global.imageTag }}
{{- end }}
