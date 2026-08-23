{{- define "voice-assistant-gateway.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "voice-assistant-gateway.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "voice-assistant-gateway.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "voice-assistant-gateway.labels" -}}
app.kubernetes.io/name: {{ include "voice-assistant-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "voice-assistant-gateway.selectorLabels" -}}
app.kubernetes.io/name: {{ include "voice-assistant-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "voice-assistant-gateway.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "voice-assistant-gateway.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
