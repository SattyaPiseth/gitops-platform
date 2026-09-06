# Traefik routing and backend transport concepts

This guide explains how `IngressRoute`, `IngressRouteTCP`, and
`ServersTransport` divide responsibility between HTTP routing, TCP routing,
and backend connections. It also documents the MinIO design used by this
repository. The Traefik behavior described here is verified against the
official Traefik v3.7 documentation and the cluster's installed v3.7 CRDs.

## Mental model

Separate every proxied request into an incoming connection and an outgoing
connection:

```text
Client ---- incoming connection ----> Traefik ---- outgoing connection ----> Service
```

- An `IngressRoute` understands HTTP and makes Layer 7 routing decisions.
- An `IngressRouteTCP` forwards TCP streams and makes Layer 4 routing
  decisions.
- A `ServersTransport` changes how an HTTP router connects from Traefik to an
  HTTP or HTTPS backend. It does not configure the client-facing connection.

## Layer 4 and Layer 7

TCP operates at Layer 4. It supplies a reliable byte stream between IP
addresses and ports, but it does not understand HTTP paths, methods, headers,
cookies, or status codes.

HTTP operates at Layer 7. An HTTP-aware proxy can inspect requests such as:

```http
GET /api/projects HTTP/1.1
Host: application.k8s.tss.local
```

This distinction determines which Traefik route type to use.

## TLS, SNI, and certificate SANs

TLS negotiation happens before an HTTPS request becomes visible. During the
handshake, the client normally sends a Server Name Indication (SNI) value. The
server presents a certificate, and the client verifies:

1. the certificate chain terminates at a trusted CA;
2. the certificate is currently valid;
3. the requested hostname appears in a certificate Subject Alternative Name
   (SAN).

Multiple DNS names can resolve to the same Traefik address. Traefik can select
a TCP backend from SNI without decrypting the HTTP traffic.

The `Host` matcher reads the HTTP `Host` header after TLS termination. The
`HostSNI` matcher reads the hostname from the TLS handshake.

## IngressRoute: HTTP-aware routing

`IngressRoute` is Traefik's Layer 7 HTTP routing custom resource.

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: application
  namespace: application
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`application.k8s.tss.local`) && PathPrefix(`/api`)
      kind: Rule
      services:
        - name: application
          port: 8080
  tls:
    secretName: application-tls
```

In this design, Traefik terminates client TLS and can inspect HTTP:

```text
Client -- HTTPS --> Traefik -- HTTP or HTTPS --> application
                      |
                      +-- route by host, path, header, or method
                      +-- apply HTTP middleware
```

Use `IngressRoute` when the design needs:

- path-, header-, method-, or host-based HTTP routing;
- redirects or path rewriting;
- authentication or authorization middleware;
- rate limiting, retry, compression, or security-header middleware;
- Traefik to select and present the client-facing certificate.

Typical examples are Headlamp, Grafana, GitLab webservice, and REST APIs.

## IngressRouteTCP: TCP stream routing

`IngressRouteTCP` is Traefik's Layer 4 TCP routing custom resource.

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRouteTCP
metadata:
  name: minio-console
  namespace: minio-system
spec:
  entryPoints:
    - websecure
  routes:
    - match: HostSNI(`minio.k8s.tss.local`)
      services:
        - name: minio-console
          port: 9443
  tls:
    passthrough: true
```

With TLS passthrough, Traefik reads SNI to select a backend but does not
decrypt the connection:

```text
Client -------- original TLS connection --------> MinIO
                         |
                     Traefik routes by SNI
```

MinIO presents the certificate and terminates TLS. Normal HTTP middleware
cannot be applied because Traefik cannot inspect the encrypted HTTP request.

`IngressRouteTCP` can still attach protocol-appropriate `MiddlewareTCP`
resources. Traefik v3.7 provides TCP IP allowlisting and in-flight connection
limits; these do not provide HTTP header, redirect, or forward-auth behavior.

When TCP and HTTP routers share an entry point, Traefik evaluates TCP routers
first. It falls back to HTTP routers only when no TCP route matches.

Use `IngressRouteTCP` when:

- the backend must own TLS termination;
- end-to-end TLS is required;
- SNI or port routing is sufficient;
- the protocol is not HTTP;
- HTTP middleware is unnecessary.

Typical examples are TLS-passthrough MinIO or Vault, PostgreSQL, Redis over
TLS, LDAPS, MQTT, and other TCP protocols.

## ServersTransport: Traefik-to-backend behavior

`ServersTransport` configures only the outgoing HTTP/HTTPS connection created
by Traefik:

```text
Client -- HTTPS --> Traefik -- HTTPS --> application
                                  |
                             ServersTransport
```

Example:

```yaml
apiVersion: traefik.io/v1alpha1
kind: ServersTransport
metadata:
  name: application-backend-tls
  namespace: application
spec:
  serverName: application.application.svc.cluster.local
  rootCAs:
    - secret: application-ca
  minVersion: VersionTLS12
  insecureSkipVerify: false
```

An HTTP route associates the transport with its service:

```yaml
services:
  - name: application
    port: 443
    scheme: https
    serversTransport: application-backend-tls
```

For a `ServersTransport` in the same namespace, reference only its plain name.
The `namespace-name@kubernetescrd` form is for a transport in another namespace
and requires the Kubernetes CRD provider's `allowCrossNamespace` option. Keep
cross-namespace references disabled unless there is a deliberate, reviewed need.

A transport can configure:

- trusted backend certificate authorities;
- the backend SNI and certificate name through `serverName`;
- minimum and maximum TLS versions;
- client certificates for mutual TLS;
- HTTP/2 behavior and connection timeouts;
- connection pooling.

Keep `insecureSkipVerify: false` whenever possible. Setting it to `true`
encrypts traffic but removes backend identity verification.

Do not use `ServersTransport` with TLS passthrough. Traefik does not create or
own the TLS session in that design, so there is no Traefik backend TLS
connection for a transport to configure.

## Three TLS patterns

### TLS termination

```text
Client -- HTTPS --> Traefik -- HTTP --> application
```

Traefik presents the public certificate and can apply HTTP middleware, but the
backend connection is unencrypted.

### TLS termination and re-encryption

```text
Client -- TLS session 1 --> Traefik -- TLS session 2 --> application
```

Traefik can apply HTTP middleware, and `ServersTransport` can control backend
TLS validation. This requires the backend certificate name and CA to match how
Traefik reaches the backend.

### TLS passthrough

```text
Client -------- original TLS session --------> application
                         |
                       Traefik
```

The application presents the certificate. This provides end-to-end TLS but
does not support HTTP middleware at Traefik.

## Kubernetes Services and NetworkPolicies

Routes select Kubernetes Services, and Services maintain stable discovery and
ready pod endpoints. A route does not bypass NetworkPolicy. If a namespace has
default-deny ingress, traffic must also be allowed from the Traefik namespace
to every selected target port.

For this repository's MinIO Tenant:

| Purpose | Public hostname | Service port | Pod port |
|---|---|---:|---:|
| S3 API | `s3.k8s.tss.local` | 443 | 9000 |
| Console | `minio.k8s.tss.local` | 9443 | 9443 |

The `minio-allow-traefik` NetworkPolicy therefore allows TCP ports 9000 and
9443 from the `traefik` namespace.

## Repository MinIO design

MinIO terminates TLS for both endpoints. Traefik uses two SNI routes with
passthrough enabled:

```text
s3.k8s.tss.local
  -> Traefik websecure
  -> IngressRouteTCP minio-s3
  -> Service minio:443
  -> MinIO pod:9000

minio.k8s.tss.local
  -> Traefik websecure
  -> IngressRouteTCP minio-console
  -> Service minio-console:9443
  -> MinIO pod:9443
```

The cert-manager certificate contains both external DNS SANs. The Console is
enabled with `MINIO_BROWSER=on`, and `MINIO_BROWSER_REDIRECT_URL` identifies
its canonical external URL.

This design intentionally does not use `ServersTransport` and does not disable
certificate verification. Clients validate the certificate presented directly
by MinIO.

### Console security boundary

TLS passthrough prevents Traefik from applying HTTP authentication, header, or
rate-limit middleware to the Console. Keep the Console DNS name and Traefik VIP
restricted to trusted administrative networks, enforce strong MinIO credentials,
and do not expose the Console directly to the public Internet. Use MinIO policies
for routine users and reserve the root identity for break-glass administration.

## Selection guide

| Requirement | Preferred resource |
|---|---|
| HTTP host/path/header routing | `IngressRoute` |
| HTTP middleware | `IngressRoute` |
| Traefik terminates client TLS | `IngressRoute` |
| HTTPS from Traefik to an HTTP backend | `IngressRoute` plus `ServersTransport` when customization is required |
| Application terminates TLS | `IngressRouteTCP` with passthrough |
| End-to-end TLS without HTTP inspection | `IngressRouteTCP` with passthrough |
| PostgreSQL, Redis TLS, LDAPS, or another TCP protocol | `IngressRouteTCP` |

Use `IngressRoute` by default for ordinary websites and APIs. Choose
`IngressRouteTCP` when the backend must own TLS or the protocol is not HTTP.
Add `ServersTransport` only when Traefik creates an outgoing HTTP/HTTPS
connection that needs non-default behavior.

## Validation and troubleshooting

Check routes, Services, endpoints, policy, certificate, and MinIO health:

```bash
kubectl get ingressroute,ingressroutetcp -n minio-system
kubectl get svc,endpointslice -n minio-system
kubectl get networkpolicy minio-allow-traefik -n minio-system -o yaml
kubectl get certificate minio-server-tls -n minio-system
kubectl get tenant minio -n minio-system -o wide
kubectl get pods,pvc -n minio-system
```

Test the external endpoints:

```bash
kubectl get secret minio-server-tls -n minio-system \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/minio-ca.crt
curl --silent --show-error --output /dev/null --write-out 'Console: %{http_code}\n' \
  --cacert /tmp/minio-ca.crt https://minio.k8s.tss.local/
curl --silent --show-error --output /dev/null --write-out 'S3: %{http_code}\n' \
  --cacert /tmp/minio-ca.crt https://s3.k8s.tss.local/
```

Expected results are HTTP 200 for the Console and HTTP 403 for an
unauthenticated S3 root request. An S3 403 proves routing works; authentication
is required for S3 operations. Remove `/tmp/minio-ca.crt` after testing; it
is a public CA certificate, not a private key.

Inspect recent Traefik errors:

```bash
kubectl logs -n traefik deployment/traefik --since=10m \
  | grep -Ei 'minio|x509|invalid reference|500|502|error'
```

Common symptoms:

| Symptom | Likely cause |
|---|---|
| Traefik 404 | No matching router, wrong `Host`/`HostSNI`, or rejected route |
| Traefik 500 with an IP SAN error | HTTP re-encryption is validating a pod IP that is absent from the certificate |
| Traefik 502 or connection refused | Service target port is not listening, or the application feature is disabled |
| Timeout | Service has no ready endpoints or NetworkPolicy blocks the port |
| Browser certificate warning | Client does not trust the internal CA, or the requested hostname is missing from SANs |
| Console redirects to an internal name | Configure the application's canonical external redirect URL |

For TLS passthrough, verify the certificate actually presented by the backend:

```bash
printf '' | openssl s_client \
  -connect minio.k8s.tss.local:443 \
  -servername minio.k8s.tss.local 2>/dev/null \
  | openssl x509 -noout -issuer -ext subjectAltName
```

Avoid adding dynamic pod IP addresses to certificates. Prefer stable DNS SANs
and a routing design that preserves the intended TLS identity.

## Official Traefik references

This guide uses the following Traefik v3.7 references:

- [Kubernetes IngressRoute](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/kubernetes/crd/http/ingressroute/)
- [Kubernetes IngressRouteTCP](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/kubernetes/crd/tcp/ingressroutetcp/)
- [Kubernetes ServersTransport](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/kubernetes/crd/http/serverstransport/)
- [TCP routing rules and priority](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/tcp/routing/rules-and-priority/)
- [TCP middleware overview](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/tcp/middlewares/overview/)
