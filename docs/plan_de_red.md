# Plan de red y matriz de servicios

> Nota: este es el plan propuesto en el kit (subred 192.168.100.0/24). El equipo usó en su montaje la subred 192.168.1.0/24: master 192.168.1.26, worker1 192.168.1.27, worker2 192.168.1.28 y laptop 192.168.1.50.

Subred privada dedicada: **192.168.100.0/24** (clase C privada), IP estática en la interfaz Ethernet de cada nodo.
Interconexión: un switch Gigabit Ethernet no administrable.

## Direccionamiento

| Equipo | Rol | Hostname | IP (interfaz cableada) | Notas |
| --- | --- | --- | --- | --- |
| Mini PC A | Master (servidor K3s) | master | 192.168.100.10 | Plano de control, no ejecuta inferencia |
| Mini PC B | Worker 1 | worker1 | 192.168.100.11 | Ejecuta réplicas del servicio |
| Mini PC C | Worker 2 | worker2 | 192.168.100.12 | Ejecuta réplicas del servicio |
| Laptop | Cliente, simulador y dashboard | laptop | 192.168.100.50 | Prometheus y Grafana corren aquí |

## Matriz de servicios

| Servicio | Dónde corre | Puerto / protocolo | Función | Depende de |
| --- | --- | --- | --- | --- |
| SSH | Todos los nodos | 22/TCP | Administración remota | Red |
| API de Kubernetes (K3s) | master | 6443/TCP (HTTPS) | Los workers se registran y reciben órdenes | Red, token del clúster |
| Kubelet | Todos los nodos | 10250/TCP | El plano de control gestiona los pods | API de Kubernetes |
| Flannel VXLAN | Todos los nodos | 8472/UDP | Red de pods entre nodos | Red |
| Servicio de inferencia (edge-infer) | Pods en workers | 8000/TCP (HTTP) en el pod; 30080/TCP (NodePort) en cada nodo | Clasifica lecturas: normal, desgaste o falla inminente | Imagen importada, K3s |
| Balanceo de carga | kube-proxy en cada nodo | 30080/TCP | Reparte peticiones entre los pods vivos | K3s |
| node_exporter | Todos los nodos | 9100/TCP (HTTP) | Métricas de CPU, RAM, temperatura y uptime | Paquete prometheus-node-exporter |
| Prometheus | laptop | 9090/TCP (HTTP) | Recolecta métricas cada 5 s | node_exporter, edge-infer |
| Grafana | laptop | 3000/TCP (HTTP) | Dashboard en tiempo real | Prometheus |

## Flujo de datos

Sensor simulado (laptop) → HTTP POST /predict a 192.168.100.11:30080 o .12:30080 → kube-proxy elige un pod vivo → el pod extrae características, aplica el modelo y responde con la clase, la probabilidad y el nodo que atendió.
