# Deploying PropStory to Kubernetes

The UI is a static site (nginx) with the precomputed GDEX cells baked into the
image. CI publishes it to **`ghcr.io/gin-g/propstory-ui:latest`** on every push
that touches `web/`, `Dockerfile`, or `deploy/`.

## 1. Make the image pullable by your cluster

GHCR packages are **private by default**. Either:

**(a) Make the package public** (simplest): GitHub → your profile → Packages →
`propstory-ui` → Package settings → Change visibility → Public. Then no pull
secret is needed.

**(b) Use an image pull secret** (keep it private):
```bash
kubectl create secret docker-registry ghcr \
  --docker-server=ghcr.io \
  --docker-username=Gin-G \
  --docker-password=<a GitHub PAT with read:packages> \
  -n propstory
```
The Deployment already references `imagePullSecrets: [{name: ghcr}]`.

## 2. Apply

```bash
kubectl create namespace propstory
kubectl apply -f deploy/k8s.yaml
```

This creates a Deployment (2 replicas), a Service, and an Ingress for
**propstory.nickknows.net**.

## 3. Ingress / TLS

`deploy/k8s.yaml` assumes an ingress controller and cert-manager. Adjust to your
setup:
- Set `spec.ingressClassName` (e.g. `nginx`, `traefik`) to match your controller.
- The TLS block expects a cert-manager `ClusterIssuer` named `letsencrypt-prod`;
  change the annotation/issuer or remove the `tls:` block if you terminate TLS
  elsewhere.
- Point a DNS A/CNAME record for `propstory.nickknows.net` at your ingress IP.

## 4. Updating the data / image

- New precomputed cells: the `pipeline.yml` workflow commits `web/data/<cell>.json`;
  the next image build bakes them in. Roll out with:
  ```bash
  kubectl -n propstory rollout restart deployment/propstory-ui
  ```
  (The Deployment pins `:latest`; for reproducible rollouts, switch the image tag
  to the commit SHA tag that CI also pushes.)

## Notes
- The browser still calls out to **Nominatim** (geocoding), **GDEX/OSDF** (live
  fallback for non-precomputed cells), and **Esri** (imagery basemap). Make sure
  your network/CSP allows those, or restrict to precomputed cells only.
