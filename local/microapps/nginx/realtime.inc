# Realtime socket of app pages (ADR-0032), included in every app-origin
# server. The broker pings every 30 seconds, so the long read timeout only
# bounds a connection both sides forgot. Host stays the request's own, as in
# the server's other locations.
location = /__ics/realtime {
    proxy_pass http://ics_broker;
    include /etc/nginx/conf.d/proxy-common.inc;
    proxy_set_header Host       $http_host;
    proxy_set_header Upgrade    $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
}
