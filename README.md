# SRE mini Project

본 프로젝트는 SRE 관점에서

- 서비스 신뢰성 측정
- 관측 가능성(Observability) 구축
- 장애 유도 및 대응
- RCA 문서화

를 목표로 하는 미니 프로젝트입니다.

## 구조

![structure](images/structure.png)

---

## 1. Quick Start

### Prerequisites

- Docker
- Docker Compose (v2)

### Run the stack

```bash
git clone https://github.com/devopsjean/mini-project.git
cd <repo>
docker compose up -d
```

## 2.요구사항

### 2.1. 서비스(API) - Verification

---

본 API는 신뢰성 테스트 목적의 서비스로, 정상 응답/의도적 지연/의도적 5xx 오류를 재현할 수 있다.

#### 2.1.1 정상 응답

- Endpoint: `/health`
- Expected: HTTP 200 + JSON body

```bash
curl -i http://localhost:8080/health
```

![health](images/rep1-health.png)

#### 2.1.2 의도적인 응답 지연

- Endpoint: /slow?ms=1000
- Expected: HTTP 200, total time ≈ 1s 이상

```bash
curl -s -w '\nstatus=%{http_code} total=%{time_total}s\n' 'http://localhost:8080/slow?ms=1000' -o /dev/null
```

![slowc](images/rep1-slow.png)

#### 2.1.3 의도적인 오류

- Endpoint: /error
- Expected: HTTP 500 (intentional)

```bash
curl -i http://localhost:8080/error
```

![errorcheck](images/rep1-error.png)

### 2.2. Observability 스택

---

본 프로젝트는 Metrics 기반 관측 가능성(Observability)을 목표로 하며, 아래 구성으로 수집/시각화/알림을 구현합니다.

#### 2.2.1 Metrics: Prometheus

API는 /metrics에서 Prometheus 형식의 메트릭을 노출하며, Prometheus는 해당 엔드포인트를 scrape하여 시계열 데이터로 저장한다.
본 프로젝트에서는 API의 요청 수/지연시간/오류 응답 같은 신뢰성 지표(SLI 후보)를 수집하기 위해 Prometheus를 사용합니다.

##### 2.2.1.1 API and prometheus metrics structure

![apiprometheusmetricstructure](/images/rep2-prometheus-metrics-structure.png)

Prometheus는 기본 scrape_interval(15s)에 따라 API의 /metrics 엔드포인트를 주기적으로 수집한다.
scrape_interval=15s는 데모 환경에서 메트릭 반응성을 확보하면서 과도한 scrape 부하를 피하기 위한 기본값으로 설정하였다.

##### 2.2.1.2 API 노출(expose)

![api-metrics](images/rep2-api-metrics.png)

사용자가 확인하는 URL은 `http://localhost:8080/metrics` 이며, Prometheus는 docker network 내부에서 `http://api:8080/metrics` 를 scrape 대상으로 사용한다.

##### 2.2.1.3 prometheus 수집(scrape)

![prometheus](images/rep2-prometheus-metrics.png)

사용자가 확인하는 URL은 `http://localhost:9090/metrics` 이며, Prometheus는 docker network 내부에서 `http://prometheus:9090/metrics` 를 scrape 하는 주체로 사용한다.

##### 2.2.1.4 query at prometheus graph

![query](images/rep2-query.png)

- http_requests_total: Counter (누적 요청 수)
- http_request_duration_seconds: Histogram (지연시간 분포)

Counter는 누적 값으로 트래픽 추이를 확인하는 데 사용되며,Histogram은 p95/p99 지연시간과 같은 SLO 계산의 기반이 된다.
해당 메트릭들은 이후 SLI/SLO 정의(가용성, 지연시간) 및 Alert Rule의 기반으로 사용된다.

#### 2.2.2 Visualization: Grafana

![visualization](images/rep2-visualizationgranafa.png)

Grafana는 UI에서 수동으로 Data source / Dashboard를 생성하지 않고, Provisioning(코드 기반 설정) 으로 자동 구성되도록 설계하였다. 목표는 `docker compose up -d` 한 번으로 동일한 관측(Visualization) 환경이 재현되게 하는 것이다.

이는 환경 차이로 인한 관측 편차를 제거하고, 실험 및 장애 재현시 동일한 기준선(baseline)을 유지하기 위함이다.

##### 2.2.2.1 Data source provisioning

- Prometheus data source를 UID기준(uid: prometheus) 으로 고정하여, 대시보드가 안정적으로 참조할 수 있게 구성하였다.
- Prometheus URL은 docker netwrok 내부 서비스명 기반으로 설정한다: `http://prometheus:9090`

  ```yaml
  apiVersion: 1
  datasources:
  - name: prometheus
    uid: prometheus
    url: http://prometheus:9090
  ```

- Grafana 대시보드는 내부적으로 datasource를 name이 아닌 UID 기준으로 참조하므로, UID를 고정하지 않으면 재기동 또는 환경 재구성 시 참조 오류가 발생할 수 있다.

See the full configuration here:

- [grafana/provisioning/datasources/prometheus.yml](grafana/provisioning/datasources/prometheus.yml)

##### 2.2.2.2 Dashboard provisioning

- Grafana 기동 시 grafana/dashboards/ 디렉터리의 JSON 대시보드(예: sre-dashboard.json)를 자동 로딩한다.

- 로딩된 대시보드는 Grafana UI에서 mini-project 폴더 아래에 나타난다.

    ```yaml
    apiVersion: 1
    
    providers:
      - name: "mini-project"
        type: file
        folder: "mini-project"
        folderUid: "mini-project"
        editable: true
        updateIntervalSeconds: 30
        options:
          path: /var/lib/grafana/dashboards
    ```

See the full configuration here:

- [grafana/provisioning/datasources/dashboard.yml](grafana/provisioning/datasources/dashboard.yml)

##### 2.2.2.3 Dashboard panel configuration

- 기본 대시보드에는 다음 3개의 패널을 포함한다.

1. **Traffic (RPS)**

    ```json
     "title": "Traffic (RPS)",
      "type": "timeseries",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "targets": [
        {
          "expr": "sum(rate(http_requests_total[1m]))",
          "refId": "A"
        }
      ],
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 16 }
    ```

    Traffic 패널은 API에 유입되는 요청량을 초당 요청수(RPS) 기준으로 시각화 한다.
    요청량의 변화는 서비스 부하 상태를 판단하는 기본 관측 지표로 활용한다.

    Traffic은 Google SRE에서 정의한 Golden Signals 중 하나로, 시스템 부하 변화의 1차 지표로 활용된다.

1. **Error Rate (5xx)**

    Error Rate 패널은 전체 요청 대비 HTTP 5xx 응답 비율을 나타낸다.
    서버 오류는 사용자 경험에 직접적인 영향을 미치므로 핵심 관측 지표로 설정하였다.
    이후 Alerting 단계에서는 이 Error Rate를 기반으로 임계치 초과 시 알림이 발생하도록 설계한다.

    ```json
    "title": "Error Rate (5xx)",
      "type": "timeseries",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "targets": [
        {
          "expr": "sum(rate(http_requests_total{status=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))",
          "refId": "A"
        }
      ],
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 8 }
    ```

    현재 환경에서는 HTTP 5xx 응답이 발생하지 않아 에러율은 0에 수렴하는 값을 보인다. 이는 서비스가 정상 상태임을 의미하며, 장애 발생 시 해당 패널을 통해 즉각적인 이상 탐지가 가능하다.

1. **Latency (p95)**

    평균 지연시간은 일부 느린 요청을 가릴 수 있으므로, 히스토그램 기반 p95 지연시간을 사용하여 상위 지연 요청을 기준으로 서비스 응답성을 관측하였다.

    p95 지연시간은 평균값이 숨길 수 있는 tail latency를 드러내며,사용자 체감 성능을 평가하는 데 더 적합하다.

    ```json
      "title": "Latency p95 (Histogram)",
        "type": "timeseries",
        "datasource": {
          "type": "prometheus",
          "uid": "prometheus"
        },
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
            "refId": "A"
          }
        ],
        "gridPos": { "h": 8, "w": 24, "x": 0, "y": 0 }
    ```

    - API 요청 시 p95 지연시간이 시간 흐름에 따라 변화
    - Histogram 기반 metric이 정상적으로 집계됨을 확인

1. **결과 요약**

    ![granafadashboard](/images/rep2-granafadashboard.png)

    위 구성을 통해 API 서비스에 대한 트래픽, 오류, 지연시간을 Grafana 대시보드에서 통합적으로 관측할 수 있음을 확인. 이는 Prometheus 기반 메트릭 수집과 Grafana 시각화가 정상적으로 연동되었음을 의미하며, 서비스 상태를 실시간으로 파악할 수 있는 기본적인 Observability 환경을 구축하였다.

    이 시각화 구성을 기반으로, 다음 단계에서는 Prometheus Alert Rule과 Alertmanagerf를 통해 이상 상태를 자동으로 감지하고 대응하는 Alerting 흐름을 구성한다.

    See the full configuration here:

    - [grafana/provisioning/dashboards/sre-dashboard.json](grafana/provisioning/dashboards/sre-dashboard.json)

#### 2.2.3 Alerting: Prometheus Alert Rule 또는 Grafana Alert

본 프로젝트에서는 서비스 신뢰성 위반을 감지하기 위해 Prometheus Alert Rule을 사용한다. Alert는 SLI 후보지표(Availability, Error Rate, Latency)를 기반으로 정의되며, Grafana는 Alert 분석을 위한 시각화 도구로 활용된다.

주요 Alert는 다음과 같다:
    - API Down (Availability)
    - High Error Rate (5xx)
    - High Latency (p95)

Prometheus는 Alert Rule을 평가하여 Alert 이벤트를 생성하지만, 실제 알림 전송(Mail, Slack 등), 그룹화, 중복제거는 Alertmanager가 담당한다.

##### 2.2.3.1 Alerting Architecture

![alteringarchitecture](/images/rep2-alertingarchitecture.png)

본 프로젝트에서는 서비스 신뢰성 위반을 감지하기 위해 Prometheus Alert Rule을 사용한다.
Alert는 SLI 후보 지표인 Availability, Error Rate, Latency를 기반으로 정의된다.

##### 2.2.3.2 Alert Validation Summary

- Prometheus가 alert-rules.yml에 정의된 규칙을 정상적으로 평가함을 확인.
- Alert는 Inactive -> Firing -> Resolved 상태 전이를 의도한 대로 수행하였다.
- Alertmanager는 수신된 Alert를 설정된 기준에 따라 정상적으로 라우팅 및 그룹화하였다.
- Alert 전달은 로컬 webhook receiver를 통해 검증되었으며, HTTP 200을 통해 실제 전송이 이루어졌음을 확인.
- 외부 서비스 (Slack, Email 등)에 의존하지 않고도 Alert 평가 및 전달 과정을 완전 재현 가능하게 구성하였다.

1. **Validation Scope**

    - Rule evaluation
        ![ruleevaluation](/images/rep2-ruleevaluation-alert.png)
        ![ruleevaluation](/images/rep2-ruleevaluation-rule.png)
        Prometheus가 alert-rules.yml에 정의된 규칙을 정상적으로 평가함을 확인.

        TestAlwaysFiring Alert는 Alert Delivery pipeline 검증을 위한 용도로 사용하였으며, 검증 이후에는 rule을 비활성화하고 prometheus를 재시작하여 기존 Alert 상태를 초기화하였다.

    - State transition
        ![statetransition](/images/rep2-statetransition.png)

    - Routing/ Grouping
        - Alertmanager 로그를 통해 APIDown Alert가 정상적으로 수신 되었으며, 설정된 'route' 및 'group_by'정책에 따라 집계(aggregation) 및 처리됨을 확인.

    - Delivery
        ![delivery](/images/rep2-delivery.png)
        - Alertmanager 로그에서 APIDown Alert에 대해 `receiver=local-webhook`으로 전송이 수행되었고 `Notify success`가 기록된 것을 확인.
        - Webhook receiver 로그에서 APIDown Alert가 포함된 payload(JSON)를 수신했으며, 해당 요청에 대해 HTTP 200 응답을 반환하여 전달 성공을 검증하였다.

1. **Validation Result**

    - Alert는 Inactive → Firing → Resolved 상태 전이를 의도한 조건에 따라 정확히 수행하였다.
    - Alertmanager는 설정된 route 및 group_by 정책에 따라 Alert를 정상적으로 처리하였다.
    - Webhook receiver는 Alert payload를 정상적으로 수신하였으며, HTTP 200 응답을 통해 전달 성공을 확인.

1. **Reproducibility**

    본  Alert 검증 환경은 외부 Slack, Email 등의 알림 채널에 즤존하지 않고 Local webhook receiver를 사용하여 구성하였다.

    Alert rule, Alertmanager 설정, webhook receiver는 docker-compose 기반으로 정의 되어 있으며, 동일한 환경을 구성할 경우 누구나 동일한 Alert 검증 과정을 재현할 수 있다.

##### 2.2.3.3 Validation Evidence

Alert validation 과정에서 다음과 같은 증적을 확보하였다.

- **Alert State Trasition**
    Prometheus Alerts UI를 통해 APIDown Alert가 Iantive -> Pending -> Firing 상태로 전이 되는 것을 확인 하였다.

- **Alert Delivery**
    Alertmanager 로그를 통해 APIDown Alert가 정상적으로 수신되었으며, 설정된 route 및 group-by 정책에 따라 local-webhook receiver로 전달됨을 확인.
    1. Alertmanager log
        ![alertmanagerlog](/images/rep2-alertmanager-logs.png)
    1. Webhook Log
        ![webhooklog](/images/rep2-webhook-log.png)
        - Alertmanager가 local-webhook receiver로 APIDown Alert를 POST 방식으로 전달하였다.
    1. Alert payload JSON(excerpt)
        Alertmanager가 webhook receiver로 전달한 Alert payload(JSON)

        ```json
        "status": "firing"
        "labels": {
            "alertname": "APIDown"
            "instance": "api:8080"
            "job": "api"
            "severity": "critical"
        };
        ```

##### 2.2.3.4 Observation & Imporovements

- 'for' 값은 Alert 반응 속도와 noise 간의 trade-off가 존재하며, 운영환경에 따라 추가적인 튜닝이 필요하다.
- p95 latency 기준값은 초기 가설로 설정되었으며, 실제 트래픽 패턴에 따라 조정이 필요하다.
- 단일 지표 기반 Alert는 noise를 유발할 수 있으며, 향후 SLO 기반 Alert로 개선 가능하다.

### 2.3. SLI/SLO 설계

---

> 이 섹션에서는 서비스의 신뢰성을 측정하기 위한 SLI와 정량적 목표인 SLO를 정의한다.

![slilodesign](/images/rep3-slislodesign.png)
Figure: Relationship between metrics, SLI/SLO, error budget, and operational decision-making

### 2.3.1 Service Scope & Definition

- **Service name**: 'fastapi-app'
- **Service type**: HTTP API service
- **Users**: internal consumers / demo users
- **Critical User Journeys**
  - (UJ-1) 'GET /health'returns '200 OK'
  - (UJ-2) Core API endpoints return successful responses within acceptable latency

Out of scope:

- Client-side network failures
- DNS resolution issues
- Non-production environments

### 2.3.2 SLI Selection Rationale

Service reliability is evaluated using indicators that are:

- **User-centric** (reflecting real user experience)
- **Measurable** (queryable via Prometheus)
- **Actionable** (can drive operation decisions)

Based on these criteria, the following SLI are selected:

- Availability (Success Rate)
- Latency (p95)
- Error Rate (5xx)

### 2.3.3 SLI Definitions

> 아래는 서비스 신뢰성을 측정하기 위해 선택한 세가지 SLI와 그 정의를 설명한다.

#### SLI-A: Success Rate (Availability)

**Definition**
Ratio of successful HTTP requests to total evaluated requests.

- **Good events**: HTTP status codes '2xx', '3xx'
- **Bad events**: HTTP status codes '5xx'
- **Excluded** '4xx' responses (treated as client-side errors by policy)

**Formula**
    ```java
    Success Rate = Good Requests/ (Good Requests + Bad Requets)
    ```

**PromQL**
    ```promql
    (
      sum(rate(http_requests_total{Pjob"fastapi", status=~"2..|3.."}[5m]]))
    )
    /
    (
      sum(rate(http_requests_total{job="fastapi", status=~"2..|3..|5.."}[5m]))
    )
    ```

#### SLI-2: Request Latency(p95)

**Definition**
95th percentile of HTTP request latency measured using histogram metrics.
    - Captures tail latency experienced by users
    - Calculated across all relevant requests

**PromQL**
    ```promql
      histogram_quantile(
        0.95,
        sum by (le) (
          rate(http_request_duration_seconds_bucket(job="fastapi"}[5m]))
        )
    )

#### SLI-3: Error Rate (5xx)

**Definition**
Ratio of server-side error responses (HTTP 5xx) over total incoming requests.
    - provides direct visibility into service failures
    - Complements availability SLI with explicit falilure tracking

**Formula**
    ```java
    Error Rate = 5xx Requests / Total Requests
    ```

### 2.3.4 SLO definitions

#### SLO-1: Availability

- **SLI**: Success Rate
- **Objective** : ≥ 99.9%
- **Time window**: Rolling 30days
- **Scope**: All service endpoints

#### SLO-2: Latency

- **SLI**: Request Latency (p95)
- **Objective**: ≤ 300ms
- **Time window**: Rolling 30days
- **Scope**: Critical user-facing endpoints

#### SLO-3: Error Rate

- **SLI**: Error Rate (5xx)
- **Objective**: ≤ 0.1%
- **Time windows**: Rolling 30 days
- **Scope**: All service endpoints

### 2.3.5 SLO Summary Table (Revised)

| SLO ID | SLI           | Good Event           | Bad Event   | Target  | Window |
|--------|---------------|----------------------|-------------|---------|--------|
| SLO-1  | Success Rate  | HTTP 2xx, 3xx        | HTTP 5xx    | ≥ 99.9% | 30d    |
| SLO-2  | Latency (p95) | Request ≤ 300ms      | N/A         | ≤ 300ms | 30d    |
| SLO-3  | Error Rate    | HTTP non-5xx         | HTTP 5xx    | ≤ 0.1%  | 30d    |

### 2.3.6 Error Budget

Error Budget은 정의된 **SLO를 기준으로 허용 가능한 실패 범위**를 의미하며, 서비스 신뢰성을 운영 관점에서 판단하기 위한 기준선 역할을 한다. 이는 시스템에 강제로 적용되는 규칙이 아니라, 운영 의사결정을 돕기 위한 설계 개념이다.

본 프로젝트에서 정의한 SLO의 시간범위(rolling 30 days)를 기준으로, Error Budget은 다음과 같이 계산된다.

- **Error Budget = 1 - SLO Target**

앞서 정의한 Availability SLO (SLO-1)를 기준으로 하면:

- **Availability SLO (SLO-1)**: ≥ 99.9%
- **허용 가능한 Error Budget**: 30일 기분 전체 요청 중 최대 0.1%

즉, SLO 평가 기간 동안 전체 요청 중 최대 0.1%ㄲ지의 HTTP 5xx 오류는 Availability SLO 위반으로 간주되지 않는다.

#### 운영 관점에서의 해석

Error Budget은 서비스 운영 시 우선 순위를 결정하기 위한 기준으로 활용된다.

- Error Budget은 소모 속도가 빠를 경우, 신규 기능 개발보다는 안정성 개선과 장애 원인 분석을 우선한다.
- Error Budget이 안정적으로 유지되는 경우, 기능 개발 및 배포를 정산적으로 진행할 수 있다.

본 문서에서는 Error Budget을 설계 수준에서 정의하여, SLO 기반 Alerting 및 향후 운영 정책으로 확장할 수 있는 기초 기준을 마련하는 데 목적이 있다.

### 2.4. 장애 시나리오 및 Incident Response

---

이 섹션에서는 서비스 운영 중 발생할 수 있는 장애를 의도적으로 재현하고, 장애 감지부터 복구 및 학습까지의 Incident Response 흐름을 SRE 관점에서 정리한다. 본 목적은 장애 자체가 아니라, 장애를 어떻게 인지하고 관리했는지를 보여주는 데 있다.

#### 2.4.1 Incident Scenario Overview

##### 2.4.1.1 **목적**

본 장애 시나리오의 목적은 실제 운영 환경에서 발생할 수 있는 단일하고 현실적인 장애 상황을 재현하고, 사전에 정의한 SLI/SLO 기반 Alert이 정상적으로 동작하는지를 검증하는 데 있다.

구체적으로는 다음을  목표로 한다.

- 실제 운영 환경에서 발생 할 수 있는 현실적인 단일 장애를 선택
- 기존에 정의한 SLI/SLO와 직접적으로 연결되는 장애 상황 재현
- 장애 발생 부터 Alert -> Response -> Recovery까지의 Incident Response 흐름 검증.

본 섹션은 장애를 '만드는 것'이 아니라, 장애를 어떻게 인지하고 관리했는지를 보여주는 데 중점을 둔다.

#### 2.4.2.2 **선택한 장애 시나리오**

- Scenario:  API서버에서 HTTP 5xx 오류 지속 발생하는 상황
- 유형: Server-side failure
- 의도: Availability/ Error Rate SLI 위한 상황 재현

본 시나리오는 서비스 신뢰성에 직접적인 영향을 주는 대표적인 서버 장애 유형으로, 사용자 관점에서 "요청이 실패한다"는 명확한 증상을 가지며, Availability SLO 및 Error Rate와 명확하게 연결된다.

> 시스템 복잡도를 최소화하기 위해 본 실험에서는 단일 장애 시나리오만을 대상으로 한다.

#### 2.4.2 Failure Injection(장애 유도)

##### 2.4.2.1 **장애 유도 방식**

장애는 API 서비의 `/error` 엔드포인트를 활용하여 의도적으로 HTTP 500 응답을 일정 시간동안 반복 요청을 발생시켜 의도적으로 오류 트래픽을 유지.

- `/error` 엔드포인트 호출시 항상 HTTP 500 반환

    ```bash
    curl -i http://localhost:8080/error
    ```

    ![curl500error](/images/rep4-2421-curl500error1.png)
- 일정 시간 동안 반복적인 요청을 발생 시켜 Error Rate 상승 유도

  - 아래 명령은 일정 시간 동안 오류 요청을 반복 발생시켜 Error Rate SLI가 Alert Rule 조건을 충족하도록 설계했다.
  
    ```bash
    docker compose run --rm loadgen sh -lc '
    end=$(( $(date +%s) + 120 ))
    i=0
    while [ $(date +%s) -lt $end ]; do
      i=$((i+1))
      code=$(curl -s -o /dev/null -w "%{http_code}" http://api:8080/error)
      printf "%s #%03d code=%s\n" "$(date "+%H:%M:%S")" "$i" "$code"
      sleep 0.2
    done
    '
    ```

    ![curl500error](/images/rep4-2421-curl500error2.png)

- 정상 트래픽과 구분되는 의도적 서버 오류 패턴 생성

    ![curl500error](/images/rep4-2421-curl500errorpattern.png)

본 장애 유도 방식은 재현 가능하며, 실험 종료 후 즉시 정상 상태로 복구할 수 있도록 설계되었다. 동일한 docker-compose 환경에서는 별도 도구 설치 없이 누구나 재현 가능하다.

##### 2.4.2.2 **기대 효과**

- HTTP 5xx 응답 증가로 Error Rate (5xx) SLI상승
- Availability SLO에 영향을 주는 조건 충족
- Error Rate 기반 Prometheus Alert Rule 트리거

이를 통해 Alert가 단순한 임계치 초과가 아니라, SLO 보호 목적에 따라 정상적으로 동작하는지를 검증할 수 있다.

> 본 장애는 실험 목적에 한해 의도적으로 주입되었으며, 동일한 환경에서는 누구나 재현 가능하도록 설계되었다.

#### 2.4.3 Detection (장애 감지)

##### 2.4.3.1 **감지 수단**

본 장애는 Prometheus Alert Rule(alert-rules.yml)을 통해 감지되었다.

- **Alerting system**: Prometheus Alert Rule

    ```yaml
    - alert: HighErrorRate
        expr: |
          (
            sum(rate(http_requests_total{status=~"5.."}[5m]))
            /
            sum(rate(http_requests_total[5m]))
          ) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High 5xx error rate detected"
          description: "More than 5% of requests are failing with 5xx errors."
    ```

- Alert name: 'HigherrorRate'

  ![alertnamehigherrorrate](/images/rep4-2422-alertnamehigherrorrate.png)

해당 Alert는 API 서비스의 Error Rate (HTTP 5xx)를 지속적으로 관측하며, 사전에 정의한 SLI/SLO 기준을 벗어나는 경우 Incident를 감지하도록 설계되었다.

##### 2.4.3.2 **감지 과정**

장애 유도 이후 다음과 같은 감지 과정이 수행되었다.

- API 서버에서 HTTP 5xx 응답이 지속적으로 발생

  ```bash
  docker compose -f --timestamps api
  ```

  ![api500logs](/images/rep4-2422-api500logs.png)

- Error Rate (5xx) SLI가 정의된 임계치를 초과

    ```bash
    docker compose exec -T prometheus sh -lc '
    for i in $(seq 1 120); do
    ts=$(date -Iseconds)
    echo "===== $ts ====="
    wget -qO- "http://localhost:9090/api/v1/alerts" \
      | tr "," "\n" \
      | sed -n -e "/\"alertname\":\"HighErrorRate\"/p" -e "/\"state\":\"/p" -e "/\"activeAt\"/p"
    echo
    sleep 5
    done
    '
    ```

  ![exceedingthreshold](/images/rep4-2422-exceedingthreshold.png)

    본 증적에 사용된 모든 타임스탬프는 Prometheus의 설계에 따라 UTC 기준으로 표시되었다.

    Prometherus는 5분 슬라이딩 윈도우를 기준으로 Error Rate(5xx) SLI를 지속적으로 평가하였다. 계산된 오류 비윺이 정의된 임계치(0.05를 초과한 상태가 2분 이상 유지되면서 highErrorRate Alert는 Pending상태에서 firing 상태로 전환되었으며, 이는 Prometheus Alerts API를 통해 확인되었다.

- Prometheus Alert Rule 평가 결과에 따라 Alert 상태 전이 발생

  ![higherrorratealert](/images/rep4-2422-higherrorrategalert.png)
Alert의 상태는 다음 순서로 전이 되었다.

  > Inactive -> Pending -> Firing

HighErrorRate Alert는 Prometheus Alerts API를 통해 평가되었다.
캡처된 출력에서 확인할 수 있듯이, Error Rate(5xx)가 정의된 임계치(5%)를 초과한 이후
해당 상태가 설정된 기간(for: 2m) 동안 지속되면서 Alert가 Firing 상태로 전환되었다.
또한 activeAt 타임스탬프를 통해, 조건이 Alert를 트리거하기에 충분한 시간 동안
유지되었음을 확인할 수 있다.

이는 일시적인 오류가 아닌, 지속적인 SLI 위한 상황임을 확인하기 위한 'for'조건이 정상적으로 적용되었음을 의미한다.

##### 2.4.3.3 **감지 시간**

- 장애 발생 시점 기준 약 N분후 Alert가 Firing 상태로 전이.
  ![statetransition](/images/rep4-2433-statetransition.png)
  
- 감지 지연은 Alert Rule에 정의된 'for' 조건에 따른 정상적인 동작으로 판단 된다. HigherrorRate Alert는 Error Rate(5xx)가 임계치를 초과한 시점부터 즉시 Firing되지 않고, 우선 Pending tkdxofh dbwlehlau, goekd whrjsdl tjfwjdehls tlrks('for: 2m')동안 지속되는지 평가한 이후 Firing 상태로 전환된다.
  ![normaloperation](/images/rep4-2433-normaloperation.png)
  위 Alert rule 정의에서 확인할 수 있듯이, HighErrorRate Alert에는 'for: 2m' 조건이 명시되어 있으며, 이는 임계치 초과 상태가 일정 시간 이상 지속되는 경우에만 Alert를 firing하도록 설계된 조건이다.

본 감지 시간은 **즉각적인 반응성과 Alert noise 최소화 간의 trade-off**를 고려한 설계 결과이다. 일시적인 오류로 인한 불필요한 Alert 발생을 방지하고, Availabiliy SLO를 안정적으로 보호하기 위한 목적에서 Error Rate SLI를 기준으로 Alert가 설계되었다.

> 본 Alert는 단순히 특정 임계값을 초과했기 떄문에 발생한 것이 아니, Availability SLO를 보호하기 위해 Error Rate SLI를 기준으로 설계된 Alert이다.

#### 2.4.4 Impact Analysis (영향 분석)

##### 2.4.4.1 **사용자 영향**

이번 장애로 인해 일부 API 요청이 HTTP 500 응답으로 실패아였으며, 이에 따라 정산적인 응답을 기대하는 클라이언트 요청 처리가 불가능한 상태가 발생하였다. 사용자 관점에서는 요청실패가 즉시 인지 가능한 수준의 영향으로 나타났다.

- 일부 API 요청이 HTTP 500 응답으로 실패
  ![api500internalservererror](/images/rep4-2441-api500internalservererror.png)
  API 서버 로그에서 다수의 요청이 HTTP 500응답으로 실패한 것을 확인하였다. 이는 서버가 정상적인 요청을 처리하지 못한 상태였음을 의미한다.

- 정상 응답을 기대하는 클라이언트 요청 처리 불가
  - 클라이언트 관점에서 API 요청을 수행한 결과, HTTP 응답이 반환되어 요청 처리가 실패하였다. 이는 호출 주체가 명시적으로 오류를 인지할 수 있는 형태의 실패이다.

- 사용자 관점에서 요청 실패가 명확하게 인지되는 상태
  ![internalserver500error](/images/rep4-2441-internalserver500error.png)
  HTTP 500응답은 클라이언트에게 명시적으로 오류 상태를 전달하는 응답으로, 사용자또는 호촐 주체가 요청 실패를 즉시 인지할 수 있는 상태이다. 본 장애는 사용자 관점에서도 요청 실패가 명확히 들러나는 형태로 영향을 미쳤다.

> 장애 발생 전후 특정 시간 범위의 API 서버 로그를 확인한 결과, 해당 구간에서 다수의 HTTP 500 응답이 발생한 것을 확인하였다. 이는 서버가 정상적인 요청을 처리하지 못한 상태였음을 의미한다.
본 장애는 서버 측 오류로 인해 발생하였으며,클라이언트 재시도 여부와 관계없이 사용자 또는 외부 시스템 입장에서는 서비스 신뢰성 저하로 인식될 수 있는 장애로 분류된다.

##### 2.4.4.2 **SLO 영향**

본 장애는 사전에 정의한 SLO 중 Availability SLO 및 Error Rate SLI에 영향을 미쳤다.
(참고: [2.3 SLI/SLO 설계](#23-slislo-설계))

![grafana](/images/rep4-2443-grafanaerrorrate.png)

- **Availability SLO**

  - 장애 지속 시간 동안 성공 요청 비율이 감소하여 SLO 위반 또는 위반에 근접한 상태로 평가된

- **Error Budget 소모 발생**
  - Error Rate(5xx)가 0.6이상으로 상승한 구간이 관측되었으며, Availability. 정의(1 - error Rate)에 따라 성공 성공 요청 비율은 40% 이하로 급격히 감소한 상태로 해벅할 수 있다.
  
  앞서 정의한 Availability SLO는 Success Rate를 기준으로 하며
  (참고: [2.3.4 SLO definitions](#234-slo-definitions),
  [2.3.5 SLO Summary Table](#235-slo-summary-table-revised)),
  Availability는 Error Rate의 보완 지표(1 − Error Rate)로 해석된다.

본 장애는 시전에 정의한 Availability 및 Error Rate SLI에 영향을 미쳤다. 장애 구간 동안 HTTP 5xx dㅡㅇ답이 지속적으로 발생함에 따라, 성공 요청 비율이 감소하여 Availability SLO 위반 또는 위반에 근접한 상태로 평가될 수 있다.

또한 Error Rate 증가로 인해 Error Budget이 일부 소모되었으며, 이는 단일 장애 이벤트 자체보다는 SLO 평가 기간(Rolling window) 내에서의 누적 신뢰성 지표 관점에서 판단 되었다.

> 본 장애는 사용자 경험에 직접적인 영향을 주는 **신뢰성 관점의 장애**로 분류 된다.

#### 2.4.5 Response (대응)

##### 2.4.5.1 **초기 대응**

Alert 발생 이후, 우선적으로 **서비스 상태 및 장애 범위 확인**을 수행하였다.

- Grafana Dashboard를 통해 Error Rate (5xx) 및 전체 요청 상태 확인
- 장애가 단일 엔드포인트에 국한된 문제인지, 서비스 전반에 영향을 주는지 확인
- 오류가 일시적인 스파이크인지, 지속적으로 발생하는지 여부 확인

초기 대응 단계에서는 **즉각적인 조치보다 상황 파악을 우선**하여, 불필요한 대응이나 오판을 방지하는 데 중점을 두었다.

##### 2.4.5.2 **조치 내용**

장애 원인이 의도적으로 주입된 오류임을 확인한 이후, 다음과 같은 조치를 수행하였다.

- 장애유도 로직 확인
- 의도적 장애 주입 중단
  - `/error` 엔드포인트 호출 중단
  - 또는 API 서비스 재시작을 통한 정상 상태 복구

조치는 서비스의 정상 동작을 회복시키는 데 필요한 최소한의 범위로 제한하였다.

##### 2.4.5.3 **대응 방식**

- 대응 유형: 수동 대응
- 대응 기준: Runbook 기반의 표준 점검 절차 수행

본 대응은 자동 복구가 아닌, **Incident Response 흐름 검증을 위한 수동 개입**으로 수행되었다.

모든 대응 과정은 원인 분석과 재발 방지를 목적으로 하였으며, 개인 또는 특정 구성 요소에 책임을 전가하지 않는 **Blame-free 원칙**을 유지하였다.

> 본 대응 과정에서 Blame-free 원칙을 유지하였다.

#### 2.4.6 Recovery (복구)

##### 2.4.6.1 **복구 시점**

장애 유도 중단 이후 API 서비스의 정상 응답이 확인 되었으며, 이에 따라 Alert 상태가 정상적으로 해제되었다.

- 장애 유도 중단 후 정상 응답 확인
- Alert 상태 전이: 'firing -> Resolved'

이는 Error Rate SLI가 정의된 정상 범위로 복귀했음을 의미한다.

##### 2.4.6.2 **회복 지표**

복구 여부는 개별 요청의 성공 여부가 아니라, **사전에 정의한 SLI/SLO 기준**을 통해 판단하였다.

- **Error Rate SLI**: 정상 범위 복귀
- **Availability 지표**: 안정화

해당 지표들은 Grafana Dashboard 및 Prometheus 데이터를 통해 확인 되었다.

> 서비스는 정의된 **SLO 기준 내의 정상 상태로 복구** 되었다.

#### 2.4.7 Lessons Learned

##### 2.4.7.1 **잘 된 점**

- Error Rate 기반 Alert가 Availability SLO 위반 징후를 조기에 감지함
- 장애 발생 -> 감지 -> 대응 -> 복구까지의 Incident Response 흐름이 명확하게 검증됨
- SLI/SLO를 기준으로 장애의 영향과 복구 여부를 일관되게 판단할 수 있었음

본 실험을 통해 Alert가 단순한 알림이 아니라, **서비스 신뢰성을 보호하기 위한 운영 도구**로 기능함을 확인.

##### 2.4.7.2 **개선 할 점**

- 단일 지표(Error Rate) 기반 Alert은 상황에 따라 noise를 유발할 수 있음
- Alert 조건이 SLI중심으로 구성되어 있어, SLO 관점에서의 장기적 신뢰성 판단에는 한계가 존재함

이에 따라 향후에는 다음과 같은 개선 여지가 있다.

- SLO기반 Alert 도입
- Multi-window/ Multi-burn-rate Alert를 통한 false positive 감소

##### 2.4.7.3 **향후 계획**

- Latency(p95) 기반 장애 시나리오를 추가하여 응답 지연이 사용자 경험에 미치는 영향을 추가적으로 검증
- Incident Response 과정에서 반복적으로 수행되는 절차를 Runbook 형태로 문서화 및 확장

이를 통해 단일 장애 대응을 넘어, 지속 가능한 신뢰성 운영 체계로 확장하는 것을 목표로 한다.

### 2.5. RCA (Root Cause Analysis)

---

#### 2.5.1 장애 요약

본 Incident는 API 서비스에서 HTTP 5xx 오류가 지속적으로 발생한 상황을 의도적으로 재현한 실험이다.장애는 FastAPI 서비스의 `/error` 엔드포인트를 반복 호출함으로써 서버 측 오류 트래픽을 유지하는 방식으로 유도되었으며, 그 결과 Error Rate (5xx) SLI가 급격히 상승하였다.

이로 인해 사전에 정의한 Availability SLO 및 Error Rate SLI 기준을 사전에 정의한 Availability SLO 및 Error Rate SLI 기준을 기준으로, 본 장애 구간은 SLO 위반 또는 Error Budget 소모가 발생한 상태로 평가되었다.

본 Incident의 목적은 장애 자체가 아니라, SLI/SLO 기반 Alert → Response → Recovery 흐름이 실제 운영 환경과 유사하게 동작하는지 검증하는 데 있다.

#### 2.5.2 영향 범위

- **사용자 영향**
  - 일부 API 요청이 HTTP 500 응답으로 실패
  - 정상 응답을 기대하는 클라이언트 요청이 처리되지 않음
  - HTTP 500 응답 특성상, 클라이언트 또는 사용자 관점에서 요청 실패가 즉시 인지 가능한 장애로 인식됨

  본 장애는 클라이언트 네트워크 문제나 사용자 입력 오류가 아닌, **서버 측 처리 실패(Server-side failure)**로 분류된다.

- **SLO 영향**
  - Availability SLO
    - Success Rate 감소로 인해 SLO 위반 또는 위반에 근접한 상태로 평가됨

  - Error Rate SLI
    - HTTP 5xx 비율이 임계치(5%)를 초과하는 상태가 일정 시간 지속됨

  - Error Budget
    - Rolling 30일 기준 Availability SLO의 Error Budget 일부 소모

- **비영향 범위**
  - 데이터 손실 없음
  - 인프라 리소스 고갈 없음
  - 비정상 프로세스 종료 없음

  본 Incident는 단일 이벤트 자체보다는, SLO 평가 기간 내에서 신뢰성 지표가 어떻게 악화되는지를 보여주는 사례로 해석된다.

#### 2.5.3 타임라인 (Timeline)

| 단계 | 내용 |
| ------ | ------ |
| 장애 발생 | `/error` 엔드포인트 반복 호출을 통해 HTTP 500 응답 지속 발생 |
| 지표 변화 | Error Rate (5xx) SLI 상승, Success Rate 감소 |
| 감지 | Prometheus가 Error Rate SLI를 5분 슬라이딩 윈도우 기준으로 평가 |
| Pending | 임계치 초과 상태가 지속되며 Alert가 Pending 상태로 전이 |
| Firing | `for: 2m` 조건 충족 후 HighErrorRate Alert가 Firing 상태로 전이 |
| 대응 | Grafana 대시보드 및 로그를 통해 장애 범위 확인 |
| 조치 | 장애 유도 중단 (`/error` 호출 중지 또는 API 재시작) |
| 복구 | Error Rate 정상화, Alert 상태가 Resolved로 전이 |

Alert 감지까지의 지연은 Alert Rule에 정의된 'for' 조건에 따른 정상적인 동작이며,
이는 Alert noise를 줄이기 위한 의도된 설계로 판단된다. 이는 일시적인 오류로 인한 불필요한 Alert를 방지하고, Availability SLO를 안정적으로 보호하기 위한 의도된 설계로 판단된다.

#### 2.5.4 Root Cause

- **직접 원인 (Direct Cause)**
  - API 서비스의 `/error` 엔드포인트가 항상 HTTP 500 응답을 반환하도록 설계된 로직
  - 해당 엔드포인트에 대한 반복 호출로 인해 서버 오류 트래픽이 지속적으로 발생

- **근본 원인 (Root Cause)**
  - 의도적으로 주입된 서버 오류 로직이 활성화된 상태에서,
  - Error Rate SLI를 기준으로 한 Alert 조건을 충족할 만큼의 오류 트래픽이 유지됨

  이는 코드 결함이나 인프라 장애가 아닌,
  신뢰성 검증을 목적으로 한 Controlled Failure Injection의 결과이다.

#### 2.5.5 재발 방지 대책

- **단기 개선**
  - 장애 유도용 엔드포인트(`/error`)는 실험 환경에서만 활성화
  - 실험 종료 후 즉시 비활성화 또는 접근 제한
  - Runbook에 “의도적 장애 주입 여부 확인” 단계 명시

- **중·장기 개선**
  - **SLO** 기반 **Alert** 도입
    - 단일 Error Rate 임계치 Alert 대신,
    - Error Budget 소모 속도를 기준으로 한 Alert 설계

  - **Multi-window / Multi-burn-rate Alert**
    - 단기 스파이크와 지속적 장애를 구분하여 Alert noise 감소
  - **Latency 기반 장애 시나리오 추가**
    - p95 latency 상승이 사용자 경험에 미치는 영향 검증
  - **Incident 대응 절차의 Runbook화**
    - 감지 → 판단 → 대응 → 복구 단계를 명문화하여 재현성 확보
