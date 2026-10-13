# Kubernetes deployment

Manifests for API, web, ingress, HPA, ConfigMap, and secrets.

## Apply

```bash
docker build -t healthevidence-ai:0.3.0 .
docker build -t healthevidence-web:0.3.0 ./frontend

kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/configmap.yaml
# Copy secret.example.yaml, fill values, then apply
kubectl apply -f deploy/kubernetes/secret.yaml
kubectl apply -f deploy/kubernetes/api-deployment.yaml
kubectl apply -f deploy/kubernetes/web-deployment.yaml
kubectl apply -f deploy/kubernetes/ingress.yaml
```

## Auth

Set `AUTH_MODE=oidc` with issuer and JWKS URL from your identity provider.

For local clusters without an IdP, use `AUTH_MODE=dev-jwt` and `POST /api/v1/auth/dev-token`.

## Safety

Do not place real protected health information in images or plaintext secrets.
