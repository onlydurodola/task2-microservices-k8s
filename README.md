# Task 2: Microservices Deployment on Kubernetes with YugabyteDB, OPA, KEDA, and APISIX
<img width="1004" height="1050" alt="Untitled diagram-2025-10-19-211320" src="https://github.com/user-attachments/assets/ded30dd7-6ce7-4562-a238-f8a05d22e1eb" />

## Overview

This report documents the deployment of a suite of two microservices — **Inventory Service** and **Order Service** — on a **single-node MicroK8s cluster** running on an **AWS EC2 instance (Ubuntu 24.04, t3.medium)**.
The architecture integrates:

* **YugabyteDB** as the distributed database layer
* **OPA Gatekeeper** for policy enforcement
* **KEDA** for event-driven autoscaling
* **APISIX** as the API Gateway and ingress layer

Both microservices were implemented in **Python (FastAPI)** using **SQLAlchemy** to manage transactional consistency across YugabyteDB’s YSQL API.

The goal was to design and deploy a **production-like microservices environment** demonstrating distributed transactions, dynamic scaling, centralized policy enforcement, and gateway-based request routing.
All components — except for APISIX route synchronization — are currently **fully operational and verified**.

---

## Environment Summary

| Component        | Version / Details                                        |
| ---------------- | -------------------------------------------------------- |
| Kubernetes       | MicroK8s v1.25.16 (single-node)                          |
| Node             | EC2 `ip-172-31-20-243` (4 vCPU, 16 GiB RAM, 30 GiB disk) |
| Database         | YugabyteDB v2025.1.1.1-b1 (single-node YSQL)             |
| Microservices    | FastAPI — `order-service:8000`, `inventory-service:8001` |
| Supporting Tools | Helm3, kubectl, ab (Apache Benchmark)                    |

---

## 1. Cluster Preparation

Enabled MicroK8s core and community addons:

```bash
microk8s enable storage helm3 metrics-server
microk8s enable community  # For KEDA
```

Created a dedicated namespace:

```bash
kubectl create namespace task2
```

✅ **Result:** Core addons active, namespace ready.

---

## 2. YugabyteDB Deployment

Deployed via Helm with customized `values.yaml` for single-node operation:

```bash
helm repo add yugabytedb https://charts.yugabyte.com
helm install yugabyte yugabytedb/yugabyte -n task2 -f manifests/yugabyte/values.yaml --wait --timeout=10m
```

* **Adjustments:** Replicas reduced to 1, CPU/memory limits lowered, `skipUlimit` enabled.
* **Result:** Pods `yb-master-0` and `yb-tserver-0` healthy, YSQL reachable at port `5433`.

Database initialized via a Kubernetes Job:

```bash
kubectl apply -f db_init.yaml
```

✅ **Verification:** Tables created and populated with sample data.

---

## 3. Microservices Deployment

* Secrets for DB credentials and ConfigMap for inter-service communication:

  ```bash
  kubectl create secret generic db-credentials ...
  kubectl create configmap app-config ...
  ```

* Deployments applied:

  ```bash
  kubectl apply -f manifests/microservices/inventory-deploy.yaml
  kubectl apply -f manifests/microservices/order-deploy.yaml
  ```

✅ **Result:** Both services connected successfully to YugabyteDB and to each other.

**Functional Test:**

```bash
kubectl port-forward -n task2 svc/order-service 8000:8000 &
curl -X POST http://localhost:8000/order/apple/1 -H "Authorization: Bearer valid-token"
```

→ Stock deducted successfully in inventory.

---

## 4. OPA Gatekeeper (Policy Enforcement)

Installed via Helm:

```bash
microk8s helm3 repo add gatekeeper https://open-policy-agent.github.io/gatekeeper/charts
microk8s helm3 install gatekeeper gatekeeper/gatekeeper -n gatekeeper-system --create-namespace
```

Applied a **constraint template and policy** requiring all Deployments in `task2` to include the label `secure-comm: "true"`.

✅ **Result:**

* Gatekeeper pods running.
* Missing label causes denied deployment until corrected.

---

## 5. KEDA Autoscaling

Enabled and configured CPU-based autoscaling:

```bash
microk8s enable community
microk8s enable keda
kubectl apply -f manifests/keda/order-scaledobject.yaml
kubectl apply -f manifests/keda/inventory-scaledobject.yaml
```

Tested under load using Apache Benchmark:

```bash
ab -n 10000 -c 50 -p post_data.txt -T "application/json" http://localhost:8000/order/banana/1
```

✅ **Result:** Replicas scaled dynamically when CPU usage exceeded 50%.

---

## 6. APISIX API Gateway (Current Status: Partially Configured)

APISIX and its Ingress Controller were deployed successfully via the official manifests.

### ✅ Working Components

* **APISIX pods** (`apisix-gateway`, `apisix-admin`, `apisix-ingress-controller`) are running.
* **Admin API reachable** at port `9180` (responds to health checks).
* **Ingress Controller** now connects properly to Admin API (confirmed via logs — no connection errors).

### ⚠️ Current Limitation

Although the `ApisixRoute` CRDs have been created and detected by the controller:

```bash
kubectl get apisixroute -n task2
```

returns:

```
inventory-route   ["*"]   ["/stock*","/inventory*"]
order-route       ["*"]   ["/order*","/orders"]
```

…the APISIX Admin API currently shows **no synced routes**:

```bash
curl http://127.0.0.1:9180/apisix/admin/routes -H 'X-API-KEY: edd1c9f034335f136f87ad84b625c8f1'
{"list":[],"total":0}
```

This indicates that while the controller is healthy and monitoring resources, the route synchronization to the gateway has not yet occurred — likely due to a missing `ApisixClusterConfig` or `Gateway` reference.

**Next Step:**
Define a cluster-wide configuration using:

```yaml
apiVersion: apisix.apache.org/v2
kind: ApisixClusterConfig
metadata:
  name: default
spec:
  admin:
    base_url: http://apisix-admin.apisix.svc.cluster.local:9180
    admin_key: edd1c9f034335f136f87ad84b625c8f1
```

and reapply routes, which should populate them into APISIX Admin and resolve the 404 errors.

---

## 7. Summary of Challenges and Solutions

| Challenge            | Description                                  | Solution                                                        |
| -------------------- | -------------------------------------------- | --------------------------------------------------------------- |
| YugabyteDB Timeout   | Resource exhaustion, ulimit preflight errors | Single-node config, reduced resources, `skipUlimit`             |
| DB Init Host         | Invalid service DNS                          | Corrected to `yb-tserver-0.yb-tservers.task2.svc.cluster.local` |
| OPA RBAC             | Invalid user in binding                      | Group-based clusterrolebinding for `microk8s-user`              |
| OPA Validation Error | Unknown field ‘parameters’                   | Added `openAPIV3Schema` to template                             |
| KEDA Inactive        | Metrics API missing                          | Enabled `metrics-server`, adjusted load                         |
| APISIX DNS Issues    | Chart repo unreachable                       | Manual CRD apply from cloned repo                               |
| APISIX Route Sync    | Controller not populating Admin API          | Reconfigure via `ApisixClusterConfig` (next step)               |

---

## 8. Conclusion

The **YugabyteDB**, **OPA**, **KEDA**, and **microservices** layers are all verified and functioning as intended.
**APISIX** is deployed and reachable, with the Ingress Controller now properly connected to the Admin API, but **route synchronization remains pending**. Once the `ApisixClusterConfig` and cluster gateway linkage are finalized, the API Gateway will complete the routing chain.

Overall, the deployment demonstrates a **comprehensive microservices environment** integrating distributed data, governance, scaling, and gateway layers — nearly fully operational end-to-end.

