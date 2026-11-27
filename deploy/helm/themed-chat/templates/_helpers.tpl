{{- define "themed-chat.fullname" -}}
{{- if not (regexMatch "^[a-z][a-z0-9-]*$" .Release.Name) -}}
{{- fail "release name must start with a letter and contain only lowercase letters, digits, or hyphens" -}}
{{- end -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "themed-chat.selector" -}}
app.kubernetes.io/name: {{ .Chart.Name | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}
