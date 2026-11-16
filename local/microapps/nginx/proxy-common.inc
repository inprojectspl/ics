# Headers every proxied request gets. Included at http level and again in
# each location that sets its own headers: nginx drops inherited
# proxy_set_header directives as soon as a location defines one.
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Host  $http_host;
proxy_set_header X-Forwarded-Proto $scheme;
# Never let a client smuggle identity or service headers to a backend.
proxy_set_header X-ICS-Service-Token "";
proxy_set_header X-ICS-User          "";
proxy_set_header X-Forwarded-User    "";
