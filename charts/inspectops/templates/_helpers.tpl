{{- define "inspectops.labels" -}}
app.kubernetes.io/part-of: inspectops
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "inspectops.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 40 | trimSuffix "-" -}}
{{- end -}}
