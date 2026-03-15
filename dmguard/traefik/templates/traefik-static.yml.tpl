entryPoints:
  websecure:
    address: ":443"
  dashboard:
    address: ":{{DEBUG_DASHBOARD_PORT}}"

certificatesResolvers:
  letsencrypt:
    acme:
      email: "{{ACME_EMAIL}}"
      storage: "{{ACME_STORAGE_PATH}}"
      tlsChallenge: {}

providers:
  file:
    filename: "{{TRAEFIK_ROUTES_PATH}}"
    watch: true

log:
  filePath: "{{TRAEFIK_LOG_PATH}}"
  level: "INFO"

api:
  dashboard: true
  insecure: false
