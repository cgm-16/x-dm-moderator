http:
  routers:
    webhook:
      rule: "Host(`{{PUBLIC_HOSTNAME}}`) && Path(`/webhooks/x`)"
      entryPoints:
        - websecure
      tls:
        certResolver: letsencrypt
      service: dmguard
  services:
    dmguard:
      loadBalancer:
        servers:
          - url: "{{BACKEND_URL}}"
