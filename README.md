# SRE mini Project

본 프로젝트는 **SRE(Site Reliability Engineering) 관점에서** 다음의 핵심 주제를 실습하고 문서화하는 미니 프로젝트이다.

- **서비스 신뢰성 측정**
- **관측 가능성(Observability) 구축**
- **장애 유도 및 대응**
- **RCA(Root Cause Analysis) 문서화**

본 프로젝트의 목적은 특정 도구를 나열하는 것이 아니라, 서비스의 상태를 어떻게 관ㄴ하고, 이상을 어떻게 감지하며, 장애를 어떤 기준으로 분석하고 복구했는지를 설명할 수 있는 구조를 만드는 것에 있다.

## 전제 구조 (Total Structure)

The following diagram shows the end-to-end data flow from API exposure to metrics scraping and visualization.

![structure](images/structure.png)

---

## 1. Quick Start

### 1.1 사전 요구 사항 (Prerequisites)

다음 도구가 사전에 설치 되어 있어야 한다.

- `Docker`
- `Docker Compose (v2)`

### 1.2 스택 실행 (Run the stack)

아래의 명령을 실행하여 전체 Observability 스택을 기동한다.

```bash
git clone https://github.com/devopsjean/mini-project.git
cd mini-project
docker compose up -d
```

### 1.3 실행 중인 서비스 확인 (Verify Running Services)

스택 기동 후, **모든 컨테이너가 정상적으로 실행 중**인지 확인한다.

```bash
docker compose ps
```

정산적인 경우, 모든 서비스의 상태가 `Up'으로 표시되며 출력 예시는 다음과 유사하다.

```text
NAME           SERVICE        STATUS         PORTS
api            api            Up             0.0.0.0:8080→8080/tcp
prometheus     prometheus     Up             0.0.0.0:9090→9090/tcp
grafana        grafana        Up             0.0.0.0:3000→3000/tcp
alertmanager   alertmanager   Up             0.0.0.0:9093→9093/tcp
webhook        webhook        Up             0.0.0.0:9001→9001/tcp
```

### 1.4 Verify Service Endpoints

모든 컨테이너가 정상적으로 실행 중임을 확인한 후, 각 서비스의 접근 가능 여부를 아래 URL를 통해 검증한다.

- **API 상태 확인**: [http://localhost:8080/health](http://localhost:8080/health)
- **API Metric 노출**: [http://localhost:8080/metrics](http://localhost:8080/metrics)
- **Grafana UI**: [http://localhost:3000](http://localhost:3000)(기본 관리자 계정으로 접근 가능)
- **Prometheus UI**: [http://localhost:9090](http://localhost:9090)
- **Alertmanager UI**: [http://localhost:9093](http://localhost:9093)

이 단계에서 모든 Endpoint가 정상적으로 접근 가능해야 하며, 이후 Obervability 구성 및 Alert 검증 단계를 진행 할 수 있다.

## 2. 요구사항

### 2.1. 서비스(API) - Verification

---

본 API는 신뢰성 테스트 목적으로 설계된 테스트용 서비스로, 다음과 같은 세 가지 동작을 의도적으로 재현할 수 있다.

- 정상 응답
- 의도적인 응답 지연(Latency)
- 의도적인 서버 오류(HTTP `5xx`)

#### 2.1.1 정상 응답

> 아래 코드는 Endpoint 동작 설명을 위한 발췌본이며, 전체 애플리케이션 구조는 생략한다.

- Endpoint: `/health`

    ```python
    @app.get("/health")
    def health():
        return {"status": "ok"}
    ```

- 기대 결과: HTTP `200` + JSON body

    ```bash
    curl -i http://localhost:8080/health
    ```

    ![health](images/rep1-health.png)

이 `Endpoint는 Availability 확인을 위한 기준성(Baseline) 역할을 아며, 서비스가 정상 상태임을 판단하는 최소 조건으로 사용된다.

#### 2.1.2 의도적인 응답 지연

지연(Latency)이 서비스 신뢰성 지표에 미치는 영향을 관측하기 위한 Endpoint이다.

- Endpoint: `/slow?ms=1000`

    ```python
    @app.get("/slow")
    async def slow(ms: int = 300):
        await asyncio.sleep(ms / 1000.0)
        return {"status": "ok", "delay_ms": ms}
    ```

- 기대 결과: HTTP `200`, total time ≈ `1s` 이상

    ```bash
    curl -s -w '\nstatus=%{http_code} total=%{time_total}s\n' 'http://localhost:8080/slow?ms=1000' -o /dev/null
    ```

    ![slowc](images/rep1-slow.png)

이 Endspoint는 평균 응답 시간이 아닌 `p95`와 같은 tail latency 관측을 위한 실험 입력값으로 활용된다.

#### 2.1.3 의도적인 오류

서버 측 오류가 발생하는 상황을 재현하기 위한 Endpoint이다.

- Endpoint: `/error`

    ```python
    @app.get("/error")
    def error(code: int = 500):
        if code < 500 or code > 599:
            code = 500
        raise HTTPException(status_code=code, detail=f"intentional {code} error")
    ```

- 기대 결과: HTTP `500` (의도적 오류l)

    ```bash
    curl -i http://localhost:8080/error
    ```

    ![errorcheck](images/rep1-error.png)

이 Endpoint는 Error (`5xx`)상승을 의도적으로 유도하기 위해 사용되며, 이후 Availability SLI, Error Rate SLI, Alert Rule 검증의 핵심 입력으로 활용된다.

#### 2.1.4 구현 위치

API의 전체 구현은 다음 파일에서 확인 할 수 있다.

- [`api/main.py`](api/main.py)

### 2.2. Observability 스택

---

본 프로젝트는 **Metrics 기반 관측 가능성(Observability)**을 목표로 하며, 아래 구성으로 `수집(Collect) → 시각화(Visualize) → 알림(Alert)` 흐름을 단계적으로 구성한다.

#### 2.2.1 Metrics: Prometheus

본 프로젝트에서 Prometheus는 서비스 상태를 정량적으로 관측하기 위한 Metric 수집(Collet) 시스템으로 사용된다.

API 서비스는 `/metrics` Endpoint를 통해 Prometheus 형식의 Metric을 노출하며, Prometheus는 해당 Endpoint를 주기적으로 수집(`Scrape`)하여 시계열 데이터 형태로 저장한다.

본 프로젝트에서는 API의 `요청 수(Request Rate) / 지연시간(Latency) / 오류(Error Rate, HTTP '5xx')` 응답 같은 신뢰성 지표(SLI 후보)를 수집(Collect) 하기 위해 Prometheus를 사용한다.

- 요청 수 (Request Rate)
- 요청 지연시간 (Latency)
- 서버 오류 응답 (Error Rate, HTTP '5xx')

이 Metric들은 이후 단계에서
**SLI/SLO 정의, Error Budget 계산, Alert Rule설계**의 기반 데이터로 활용된다

#### 2.2.1.1 API and Prometheus metrics structure

![apiprometheusmetricstructure](/images/rep2-prometheus-metrics-structure.png)

Prometheus는 기본 설정된 `scrape_interval` 값(`15s`)에 따라 API의 `/metrics` Endpoint를 주기적으로 수집한다.
`scrape_interval=15s`는 다음의 기준으로 설정 되었다.

- 데모 환경에서 Metric의 변화가 빠르게 반영될 것
- 과도한 `Scrape`로 인한 불필요한 부하를 피할것

이는 운영 환경에서의 최적값을 의미하지 않으며, 실험 및 검증 목적에 적합한 기본값으로 선택되었다.

#### 2.2.1.2 API 노출 (expose)

![api-metrics](images/rep2-api-metrics.png)

API 서비스는 '/metrics` Endpoint를 통해 Prometheus 형식의 Metric을 노출한다.

- 사용자가 직접 확인하는 URL
  - `http://localhost:8080/metric`
- Prometheus가 실제로 scape 하는 대상
  - `http://api:8080/metrics`(Docker 네트워크 내부)

이와 같이 외부 접근 경로와 내부 수집 경로를 분리하여, 컨테이너 환경에서도 안정적으로 Metric을 수집할 수 있도록 구성하였다.

#### 2.2.1.3 prometheus 수집(scrape)

![prometheus](images/rep2-prometheus-metrics.png)

Prometheus는 Docker 네트워크 내부에서
API 서비스의 `/metrics` Endpoiint를 주기적으로 수집하는 주체로 동작한다.

- Prometheus UI 접근 URL
  - `http://localhost:9090`

이를 통해 Prometheus가 정상적으로 API Metric을 수집하고 있으며, Metric 데이터가 시계열 형태로 저장되고 있음을 확인할 수 있다.

#### 2.2.1.4 query at prometheus graph

![query](images/rep2-query.png)

수집된 Metric은 Proimetheus UI의 Graph 화면을 통해 직접 확인할 수 있다.
본 프로젝트에서 주요하게 사용되는 Metric은 다음과 같다.

- `http_requests_total`
  - 타입: `Counter`
  - 의미: 누적 요청 수
- `http_request_duration_seconds`
  - 타입: `Histogram`
  - 의미: 요청 지연시간 분포

`Counter`는 **Metric은 트래픽(Traffic) 추이와 요청량(Request) 변화**를 파악하는 데 사용되며,
`Histogram` Metric은 `P95`/ `p99` 지연(latency)시간 계산을 위한 기반 데이터로 사용된다.

이 Metric들은 이후 단계에서
**Availability, Latency, Error Rate SLI 정의 및 Alert Rule 설계**의 핵심 입력으로 활용된다.

#### 2.2.2 Visualization: Grafana

![visualization](images/rep2-visualizationgrafana.png)

Grafana는 Metric을 **사람이 해석 가능한 형태로 시각화(Visualize)**하기 위한 도구로 사용된다.
본 프로젝트에서는 Grafana UI에서 수동으로 데이터 소스나 대시보드를 생성하지 않고,
Provisioning(코드 기반 설정) 방식으로 자동 구성되도록 설계하였다.

설계의 핵심 목표는 다음과 같다.

- `docker compose up -d` 한 번으로 **항상 동일한 환경을 재현**
- 환경 차이로 인한 대시보드 편차 제거
- 장애 실험 및 재현 시 **동일한 기준선(Baseline) 유지

이는 "한 번 잘 보이는 대시보드"가 아니라,
**언제 실행해도 같은 관측 결과를 얻을 수 있는 환경**을 만드는 데 목적이 있다.

#### 2.2.2.1 Data source provisioning

Grafana의 Prometheus Data source는 UID 기준으로 고정하여 정의하였다.

- 데이터 소스 UID: prometehus
- Prometheus 접근 URL:
  - `http://prometheus:9090` (Docker 네트워크 내부)

  ```yaml
  apiVersion: 1
  datasources:
  - name: prometheus
    uid: prometheus
    url: http://prometheus:9090
  ```

Grafana 대시보드는 내부적으로 데이터 소스(Data source)를 이름(name)이 아닌 'UID' 기준으로 참조한다.

따라서, UID를 고정하지 않으면 다음과 같은 문제가 발생할 수 있다.

- Grafana 재기동 시 Data source 재생성
- Dashboard에서 Data source 참조 오류 발생
- 환경 재구성 시 시각화(Visualize) 깨짐

이를 방지하기 위해 Data source를 코드로 명시하고,
UID를 고정하여 대시 보드 참조 안정성을 확보하였다.
> 이 설정을 통해 Grafana 환경은 **상태가 아닌 선언적 구성**으로 관리 된다.

전체 설정 파일은 다음 경로에서 확인할 수 있다.
  
- [grafana/provisioning/datasources/prometheus.yml](grafana/provisioning/datasources/prometheus.yml)

#### 2.2.2.2 Dashboard provisioning

- Grafana 기동 시 `grafana/dashboards/` 디렉터리의에 위치한 JSON 형식의 대시보드(예: `sre-dashboard.json`)를 자동 로딩하도록 구성하였다.

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

- 대시보드는 Grafana UI에서 mini-project 폴더 아래에 표시된다.
- UI에서 수동 생성 없이도 동일한 대시보드 구성이 재현된다.

설정 파일은 다음 경로에서 확인할 수 있다.

- [grafana/provisioning/datasources/dashboard.yml](grafana/provisioning/datasources/dashboard.yml)

#### 2.2.2.3 Dashboard panel configuration

기본 대시보드에는 서비스 신뢰성을 관측하기 위한
**세 가지 핵심 패널**로 구성된다.

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

    Traffic 패널은 API로 유입되는 요청량을
    **초당 요청수 (Requests Per Second)** 기준으로 시각화(Visualize)한다.
      - 서비스 부하 변화 감지
      - 트래픽 패턴 파악
      - 장애 전과 후 비교 기준

    Traffic은 **Google SRE에서 정의한 Golden Signals 중 하나**로, 시스템 부하 변화의 1차 지표로 활용된다.

1. **Error Rate (5xx)**

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

    Error Rate 패널은 **전체 요청 대비 HTTP 5xx 응답 비율**을 나타낸다.
      - 서버 오류는 사용자 경험에 직접적인 영향을 미침
      - Availability SLI 및 Error Budget과 직접 연결됨
      - 이후 Alerting 단계에서 핵심 판단 지표로 사용됨
    정상 상태에서는 값이 `0`에 수렵하며,
    장애 발생 시 즉각적인 이상 징후를 확인할 수 있다.

1. **Latency (p95)**
  
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

    평균 지연시간은 일부 니름 요청을 가릴 수 있으므로,
    본 프로젝트에서는 `Histogram` 기반 `p95 지연시간`을 사용하였다.
      - tail latency 관측
      - 사용자 체감 성능 평가
      - Latency SLO 검증 기준

1. **기각화 결과 요약**

    ![grafanadashboard](/images/rep2-grafanadashboard.png)

    위 구성을 통해 API 서비스의 트래픽, 오류, 지연시간을
    단일 Grafana 대시보드에서 통합적으로 관측할 수 있음을 확인하였다.
  
    이는 Prometheus 기반 Metric 수집과 Grafana 21₩8ㅑ(Visualize)가
    정상적으로 연동되었음을 의미하며,
    서비스 상태를 실시간으로 파악할 수 있는
    `
    

    이 시각화(Visualize) 구성을 기반으로,
    다음 단계에서는 `Prometheus Alert Rule`과 `Alertmanager`를 활용하여
    이상 상태를 자동으로 감지하고 대응하는 `Alerting` 흐름을 구성한다.
  
    전체 대시보드 정의는 다음 파일에서 확인할 수 있다.
      - [grafana/provisioning/dashboards/sre-dashboard.json](grafana/provisioning/dashboards/sre-dashboard.json)

#### 2.2.3 알림 (Alerting): Prometheus Alert Rule 또는 Grafana Alert

본 프로젝트에서는 서비스 신뢰성 위반을 감지하기 위한 Alerting 메커니즘으로
Prometheus Alert Rule을 사용한다.

Alert는 사전에 정의한 SLI 후보 지표를 기준으로 설계되며,
각 지표는 서비스의 신뢰성 상태를 판단하는 명확한 신호(signal) 역할을 한다.

- Availability
- Error Rate (HTTP 5xx)
- Latency (p95)

Grafana는 Alert를 생성하는 주체가 아니라,
Alert 발생 전후의 지표 변화를 분석하고 해석하기 위한 시각화(Visualize) 도구로 활용된다.

즉,

- Prometheus: “언제 문제가 발생했는가”를 판단
- Grafana: “왜 문제가 발생했는가”를 해석

- **주요 Alert정의**
본 프로젝트에서 정의한 Alert은 다음과 같다.
  - **API Down**
    - 서비스 Availability 위반 감지
  - **High Error Rate (5xx)**
    - 서버 오류 비율 증가 감지
  - **High Latency (p95)**
    - 응답 지연 증가 감지

Prometheus는 Alert Rule을 평가하여 Alert 이벤트를 생성하며,
Alert의 **전송, 그룹화, 중복 제거**는 Alertmanager가 담당한다.

#### 2.2.3.1 Alerting Architecture

![alteringarchitecture](/images/rep2-alertingarchitecture.png)

본 Alerting 구조는 다음과 같은 흐름으로 구성된다.

- Prometheus가 Metric을 수집하고 Alert Rule을 평가
- Alert 조건 충족 시 Alert 이벤트 생성
- Alertmanager가 Alert를 수신
- Alertmanager가 설정된 정책에 따라 Alert를 라우팅 및 전달

이 구조를 통해 Alert 판단 로직과 전달 로직을 분리하여
Alert 설계의 명확성과 확장성을 확보하였다.

#### 2.2.3.2 Alert Validation Summary

Alerting 동작이 의도한 대로 수행되는지 검증하기 위해 다음 항목을 중심으로 검증을 수행하였다.

- Prometheus가 alert-rules.yml에 정의된 규칙을 정상적으로 평가함
- Alert 상태가 Inactive → Pending → Firing → Resolved로 전이됨
- Alertmanager가 Alert를 정상적으로 수신하고 라우팅함
- 로컬 webhook receiver를 통해 Alert 전달을 검증함
- 외부 Slack, Email 등 외부 의존성 없이 전체 흐름을 재현함

이를 통해 Alert 평가부터 전달까지의 전 과정을 완전 재현 가능한 형태로 구성하였다.

1. **검증 범위**

    - Alert Rule 평가
        ![ruleevaluation](/images/rep2-ruleevaluation-alert.png)
        ![ruleevaluation](/images/rep2-ruleevaluation-rule.png)
        Prometheus가 `alert-rules.yml`에 정의된 규칙을 정상적으로 평가함을 확인.

        TestAlwaysFiring Alert는 Alert Delivery 파이프라인 검증용으로 사용되었으며, 검증 완료 후에는 rule을 비활성화하고 Prometheus를 재시작하여 Alert 상태를 초기화.

    - Alert 상태 전이
        ![statetransition](/images/rep2-statetransition.png)
        Alert는 정의된 조건에 따라 다음 순서로 상태가 전이됨을 확인.
          Inactive → Pending → Firing → Resolved
        이는 Alert Rule의 `for` 조건이 일시적인 스파이크가 아닌 지속적인 이상 상태만을 감지하도록 정상적으로 동작했음을 의미.

    - Routing/ Grouping
        - Alertmanager 로그를 통해 `APIDown` Alert가 정상적으로 수신 되었으며, 설정된 'route' 및 'group_by'정책에 따라 집계(aggregation) 및 처리됨을 확인.

    - Delivery
        ![delivery](/images/rep2-delivery.png)
        - Alertmanager 로그에서 `receiver=local-webhook`으로 Alert가 전송되었고 `Notify success` 로그를 확인
        - Webhook receiver 로그에서 Alert payload(JSON)를 수신
        - HTTP 200 응답을 통해 전달 성공을 검증

      이를 통해 Alert가 실제 전달 단계까지 정상적으로 도달함을 확인하였다.

1. **Validation Result**

    - Alert는 Inactive → Firing → Resolved 상태 전이를 의도한 조건에 따라 정확히 수행.
    - Alertmanager는 설정된 route 및 group_by 정책에 따라 Alert를 정상적으로 처리.
    - Webhook receiver는 Alert payload를 정상적으로 수신하였으며, HTTP 200 응답을 통해 전달 성공을 확인.

1. **Reproducibility**

    본  Alert 검증 환경은 외부 Slack, Email 등의 알림 채널에 즤존하지 않고 Local webhook receiver를 사용하여 구성하였다.

    Alert rule, Alertmanager 설정, webhook receiver는 docker-compose 기반으로 정의 되어 있으며, 동일한 환경을 구성할 경우 누구나 동일한 Alert 검증 과정을 재현할 수 있다.

#### 2.2.3.3 Validation Evidence

Alert validation 과정에서 다음과 같은 증적을 확보하였다.

- **Alert 상태 전이**
    Prometheus Alerts UI를 통해 `APIDown` Alert가 `Inactive → Pending → Firing` 상태로 전이 되는 것을 확인 하였다.

- **Alert 전달**
    1. Alertmanager log
        ![alertmanagerlog](/images/rep2-alertmanager-logs.png)
    2. Webhook Log
        ![webhooklog](/images/rep2-webhook-log.png)
        - Alertmanager가 local-webhook receiver로 APIDown Alert를 POST 방식으로 전달하였다.
    3. Alert payload JSON(excerpt)
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

#### 2.2.3.4 Observation & Improvements

Alert 설계 및 검증 과정에서 다음과 같은 점을 확인하였다.

- `for` 값은 Alert 반응 속도와 noise 간의 명확한 trade-off가 존재함
- p95 latency 기준값은 초기 가설로 설정되었으며, 실제 트래픽 패턴에 따라 재조정이 필요함
- 단일 지표 기반 Alert는 noise를 유발할 수 있음

이에 따라 향후 개선 방향은 다음과 같다.

- SLO 기반 Alert 도입
- Multi-window / Multi-burn-rate Alert 적용을 통한 false positive 감소

#### 2.3. SLI/SLO 설계

---

> 이 섹션에서는 서비스의 신뢰성을 측정하기 위한 **SLI**와 정량적 목표인 **SLO**를 정의한다.

SLI는 *“무엇을 측정할 것인가”*에 대한 지표이며,
SLO는 *“얼마나 잘해야 하는가”*에 대한 목표이다.

![slilodesign](/images/rep3-slislodesign.png)
*Figure: Metric → SLI/SLO → Error Budget → 운영 의사결정 간의 관계*

#### 2.3.1 서비스 범위 및 정의 (Service Scope & Definition)

- **Service name**: `fastapi-app`
- **Service type**: HTTP API service
- **Users**: 내부 사용자 / 데모 사용자
- **Critical User Journeys**
  - (UJ-1) 'GET /health'요청이 `200 OK`를 반환
  - (UJ-2) 주요 API Endpoint가 허용 가능한 지연시간 내에 정상 응답

**범위에서 제외한 항목 (Out of scope)**

- 클라이언트 측 네트워크 오류
- DNS 해석 실패
- 비운영(Non-production) 환경

본 SLI/SLO는 **서버 측 서비스 품질**을 기준으로 정의되며,외부 환경 요인이나 사용자 입력 오류는 평가 대상에서 제외한다.

#### 2.3.2 SLI 선택 기준 (SLI Selection Rationale)

서비스 신뢰성은 다음 조건을 만족하는 지표를 통해 평가한다.

- User-centric
  -실제 사용자 경험을 반영할 수 있는 지표
- Measurable
  - Prometheus를 통해 정량적으로 측정 가능
- Actionable
  - 운영 의사결정(대응, 개선)에 활용 가능

이 기준에 따라 다음 세 가지 SLI를 선택하였다.

- **Availability (Success Rate)**
- **Latency (p95)**
- **Error Rate (HTTP 5xx)**

#### 2.3.3 SLI Definitions

> 아래는 서비스 신뢰성을 측정하기 위해 선택한 **세가지 SLI**와 그 정의이다.

#### SLI-A: Success Rate (Availability)

**정의**
전체 요청 중 성공적으로 처리된 요청의 비율을 의미한다.

- **Good events**: HTTP status codes `2xx`, `3xx`
- **Bad events**: HTTP status codes `5xx`
- **Excluded** `4xx` responses (정책상 클라이언트 측 오류로 간주)

**수식**

```java
Success Rate = Good Requests / (Good Requests + Bad Requets)`
```

**PromQL**

```promql
(
  sum(rate(http_requests_total{Pjob"fastapi", status=~"2..|3.."}[5m]))
)
/
(
  sum(rate(http_requests_total{job="fastapi", status=~"2..|3..|5.."}[5m]))
)
```

이 지표는 서비스의 **가용성(Availability)**을 직접적으로 나타내며, SLO 및 Error Budget 계산의 기준이 된다.

#### SLI-2: Request Latency(p95)

**정의**

Histogram Metric을 기반으로 계산한 HTTP 요청 지연시간의 95퍼센타일 값이다.

- 일부 느린 요청을 포함한 tail latency를 반영
- 사용자 체감 성능 평가에 적합

**PromQL**

```promql
  histogram_quantile(
    0.95,
    sum by (le) (
      rate(http_request_duration_seconds_bucket(job="fastapi"}[5m]))
    )
)
```

#### SLI-3: Error Rate (5xx)

**정의**

전체 요청 중 서버 측 오류(HTTP 5xx)가 차지하는 비율이다.

- 서버 처리 실패를 직접적으로 반영
- Availability SLI를 보완하는 지표

**Formula**

```java
Error Rate = 5xx Requests / Total Requests
```

#### 2.3.4 SLO Definitions

각 SLI에 대해 정량적인 목표(SLO)를 다음과 같이 정의한다.

#### SLO-1: Availability

- **SLI**: Success Rate
- **목표** : ≥ 99.9%
- **평가 기간**: Rolling 30days
- **범위**: 전체 서비스 Endpoints

#### SLO-2: Latency

- **SLI**: Request Latency (p95)
- **목표**: ≤ 300ms
- **평가 기간**: Rolling 30days
- **범위**: 주요 사용자 대상 endpoints

#### SLO-3: Error Rate

- **SLI**: Error Rate (5xx)
- **목표**: ≤ 0.1%
- **평가 기간**: Rolling 30 days
- **범위**: 서비스 전체 endpoints

#### 2.3.5 SLO 요약 표

| SLO ID | SLI           | Good Event           | Bad Event   | Target  | Window |
|--------|---------------|----------------------|-------------|---------|--------|
| SLO-1  | Success Rate  | HTTP 2xx, 3xx        | HTTP 5xx    | ≥ 99.9% | 30d    |
| SLO-2  | Latency (p95) | Request ≤ 300ms      | N/A         | ≤ 300ms | 30d    |
| SLO-3  | Error Rate    | HTTP non-5xx         | HTTP 5xx    | ≤ 0.1%  | 30d    |

#### 2.3.6 Error Budget

Error Budget은 정의된 **SLO를 기준으로 허용 가능한 실패 범위**를 의미한다.
이는 시스템에 강제로 적용되는 규칙이 아니라, **운영 의사결정을 돕기 위한 기준선**이다.

본 프로젝트에서 정의한 SLO의 시간범위(rolling 30 days)를 기준으로, Error Budget은 다음과 같이 계산된다.

- **Error Budget = 1 - SLO Target**

앞서 정의한 Availability SLO (SLO-1)를 기준으로 하면:

- **Availability SLO (SLO-1)**: ≥ 99.9%
- **허용 가능한 Error Budget**: 30일 기준 전체 요청 중 최대 0.1% 실패

즉, SLO 평가 기간 동안 전체 요청 중 최대 0.1%까지의 HTTP `5xx` 오류는 Availability SLO 위반으로 간주되지 않는다.

#### **운영 관점에서의 해석**

Error Budget은 서비스 운영 시 우선 순위를 결정하기 위한 기준으로 활용된다.

- Error Budget은 소모 속도가 빠를 경우 → 신규 기능 개발보다는 안정성 개선과 장애 원인 분석을 우선한다.
- Error Budget이 안정적으로 유지되는 경우 → 기능 개발 및 배포를 정산적으로 진행할 수 있다.

본 문서에서는 Error Budget을 설계 수준에서 정의하여, `SLO` 기반 `Alerting` 및 향후 운영 정책으로 확장할 수 있는 기초 기준을 마련하는 데 목적이 있다.

### 2.4. 장애 시나리오 및 Incident Response

---

이 섹션에서는 서비스 운영 중 발생할 수 있는 장애를 **의도적으로 재현**하고, 장애 감지부터 복구 및 학습까지의 **Incident Response 흐름**을 **SRE 관점**에서 정리한다. 본 목적은 장애 자체가 아니라, 장애를 어떻게 인지하고 관리했는지를 보여주는 데 있다.

#### 2.4.1 장애 시나리오 개요 (Incident Scenario Overview)

#### **2.4.1.1 목적**

본 장애 시나리오의 목적은 실제 운영 환경에서 발생할 수 있는 **단일하고 현실적인 장애** 상황을 재현하고, 사전에 정의한 **SLI/SLO 기반 Alert**이 **정상적으로 동작하는지를 검증**하는 데 있다.

구체적으로는 목표는 다음과 같다.

- 실제 운영 환경에서 발생 할 수 있는 현실적인 단일 장애를 선택
- 기존에 정의한 **SLI/SLO**와 직접적으로 연결되는 장애 상황 재현
- 장애 발생 부터 **Alert → Response → Recovery**까지의 **Incident Response 흐름** 검증

이 섹션은 장애를 '만드는 것'이 아니라, **장애를 어떻게 인지하고 관리했는가**를 보여주는 데 중점을 둔다.

#### **2.4.2.2 선택한 장애 시나리오**

- **시나이로**:  API서버에서 `HTTP 5xx` 오류가 지속적으로 발생하는 상황
- **장애유형**: Server-side failure
- **의도**
  - `Availability` SLI 영향 확인
  - `Error Rate` SLI 위한 상황 재현

본 시나리오는 서비스 신뢰성에 직접적인 영향을 주는 대표적인 서버 장애 유형이다.

- 사용자 관점에서 "요청이 실패한다"는 명확한 증상이 명확하게 드러남
- Availability SLO 및 Error Rate와 명확하게 연결됨.
- Alert 설계의 적절성을 검증하기에 적합함

> 시스템 복잡도를 최소화하기 위해 본 실험에서는 **단일 장애 시나리오**만을 대상으로 한다.

#### 2.4.2 장애유도 (Failure Injection)

#### **2.4.2.1 장애 유도 방식**

본 장애는 API 서비의 `/error` Endpoint를 활용하여 **의도적으로 `HTTP 500` 응답을 일정 시간동안 반복 발생**시켜 의도적으로 오류 트래픽을 유지.

- `/error` Endpoint 호출시 항상 `HTTP 500`을 반환하도록 설계됨

    ```bash
    curl -i http://localhost:8080/error
    ```

    ![curl500error](/images/rep4-2421-curl500error1.png)

- 일정 시간 동안 반복적인 요청을 발생 시켜 Error Rate 상승 유도

  - 아래 명령은 일정 시간 동안 오류 요청을 반복 발생시켜 **`Error Rate` SLI**가 **Alert Rule** 조건을 충족하도록 설계된 스크립트이다.
  
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

이 방식은 다음과 같은 특징을 가진다.

- 장애 원인이 명확하고 통제 가능함
- 실험 종료 즉시 정상 상태로 복구 가능함
- 동일한 `docker-compose` 환경에서는 별도 도구 설치 없이 누구나 동일하게 재현 가능함

즉, 실제 운영 장애를 모방하되 `시스템에 영구적인 영향을 주지 않는 안전한 장애 주입 방식`이다.

#### **2.4.2.2 기대 효과**

본 장애 유도를 통해 다음과 같은 효과를 기대할 수 있다.

- HTTP 5xx 응답 증가로 `Error Rate (5xx) SLI`상승
- Success Rate 감소로 `Availability SLO`에 영향 발생
- Error Rate 기반 `Prometheus Alert Rule` 트리거

이를 통해 Alert가 단순한 임계치 초과가 아니라, **SLO 보호 목적에 따라 정상적으로 동작하는지**를 검증할 수 있다.

> 본 장애는 실험 목적에 한해 **의도적으로 주입된 장애**이며, 동일한 환경에서는 누구나 재현 가능하도록 설계되었다.

#### 2.4.3 장애 감지 (Detection)

#### **2.4.3.1 감지 수단**

본 장애는 `Prometheus Alert Rule`을 통해 감지되었다.
Alert Rule은 (`alert-rules.yml`)에 정의되어 있으며, API 서비스의 **Error Rate (HTTP 5xx)**를 기준으로 이상 상태를 판단한다.

- **Alerting system**: `Prometheus` Alert Rule

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

  해당 Alert는 API 서비스의 Error Rate (`HTTP 5xx`)를 지속적으로 관측하며, 사전에 정의한 **SLI/SLO 기준을 벗어나는 경우 Incident를 감지**하도록 설계되었다.

#### **2.4.3.2 감지 과정**

장애 유도 이후 다음과 같은 감지 과정이 수행되었다.

- API 서버에서 `HTTP 5xx` 응답이 지속적으로 발생

  ```bash
  docker compose -f --timestamps api
  ```

  ![api500logs](/images/rep4-2422-api500logs.png)

  API 서버 로그를 통해 다수의 요청이 `HTTP 500`으로 실패하고 있음을 확인하였다. 이는 서버 측 오류가 지속적으로 발생하고 있음을 의미한다.

- Error Rate (5xx) SLI가 정의된 임계치를 초과

  아래 명령은 Prometheus Alerts API를 주기적으로 조회하여 `HighErrorRate` Alert의 상태 변화를 확인하기 위한 스크립트이다.

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

    본 증적에 사용된 모든 타임스탬프는 Prometheus의 설계에 따라 **UTC 기준**으로 표시되었다.

    Prometherus는 **5분 슬라이딩 윈도우**를 기준으로 `Error Rate(5xx)` SLI를 지속적으로 평가하였다. 계산된 오류 비윺이 정의된 임계치(0.05를 초과한 상태가 2분 이상 유지되면서 highErrorRate Alert는 `Pending`상태에서 `firing` 상태로 전환되었다.

    이는 Prometheus Alerts API를 통해 확인되었다.

- Prometheus Alert Rule 평가 결과에 따라 Alert 상태 전이 발생

  ![higherrorratealert](/images/rep4-2422-higherrorrategalert.png)

    Alert의 상태는 다음 순서로 전이 되었다.

  > Inactive → Pending → Firing

    HighErrorRate Alert는 Prometheus Alerts API를 통해 평가되었다.
    캡처된 출력에서 확인할 수 있듯이, Error Rate(5xx)가 정의된 임계치(5%)를 초과한 이후
    해당 상태가 설정된 기간(for: 2m) 동안 지속되면서 Alert가 Firing 상태로 전환되었다.
    또한 activeAt 타임스탬프를 통해, 조건이 Alert를 트리거하기에 충분한 시간 동안
    유지되었음을 확인할 수 있다.

    이는 일시적인 오류가 아닌, 지속적인 **`SLI 위한 상황**임을 확인하기 위한 'for'조건이 정상적으로 적용되었음을 의미한다.

#### **2.4.3.3 감지 시간**

장애 발생 시점 기준 약 **N분후** Alert가 `Firing` 상태로 전이되었다.
  ![statetransition](/images/rep4-2433-statetransition.png)
  
이 감지 지연은 Alert Rule에 정의된 'for' 조건에 따른 정상적인 동작으로 판단 된다.

`HigherrorRate` Alert는 Error Rate(5xx)가 임계치를 초과한 시점부터 즉시 `Firing`되지 않는다.
우선, `Pending` 상태로 유지되며, 해당 조건이 **2분 이상 지속되는지**를 평가한 이후에 `Firing` 상태로 전환된다.
  ![normaloperation](/images/rep4-2433-normaloperation.png)
  위 Alert rule 정의에서 확인할 수 있듯이, HighErrorRate Alert에는 'for: 2m' 조건이 명시되어 있으며, 이는 임계치 초과 상태가 일정 시간 이상 지속되는 경우에만 Alert를 firing하도록 설계된 조건이다.

이러한 감지 지연은 다음과 같은 설계 의도를 반영한 결과이다.

- 일시적인 오류로 인한 **Alert noise** 최소화
- 지속적인 오류만을 **신뢰성 위반**으로 판단
- **Availability SLO**를 안정적으로 보호

> 본 Alert는 단순히 특정 임계값을 초과했기 떄문에 발생한 것이 아니라, **Availability SLO를 보호**하기 위해 **Error Rate SLI**를 기준으로 설계된 **Alert**이다.

#### 2.4.4 영향 분석 (Impact Analysis)

#### 2.4.4.1 사용자 영향

이번 장애로 인해 일부 API 요청이 HTTP 500 응답으로 실패아였으며, 정상적인 응답을 기대하는 클라이언트 요청 처리가 불가능한 상태가 발생하였다.
**사용자 관점에서는 요청 실패가 즉시 인지 가능한 수준의 영향**으로 나타났다.

- **일부 API 요청이 `HTTP 500` 응답**으로 실패
  ![api500internalservererror](/images/rep4-2441-api500internalservererror.png)
  API 서버 로그에서 다수의 요청이 `HTTP 500`응답으로 실패한 것을 확인하였다.
  이는 서버가 정상적인 요청을 처리하지 못한 상태였음을 의미한다.

- **정상 응답을 기대하는 클라이언트 요청 처리 불가**
  클라이언트 관점에서 API 요청을 수행한 결과, `HTTP 500`응답이 반환되어 요청 처리가 실패하였다.
  이는 호출 주체가 명시적으로 오류를 인지할 수 있는 형태의 실패이다.

- **사용자 관점에서 요청 실패가 명확하게 인지되는 상태**
  ![internalserver500error](/images/rep4-2441-internalserver500error.png)
  `HTTP 500`응답은 서버 요류를 명확히 나타내는 상태 코드로, 사용자또는 호촐 주체가 요청 실패를 즉시 인지할 수 있는 상태이다. 본 장애는 사용자 관점에서도 요청 실패가 명확히 들러나는 형태로 영향을 미쳤다.

장애 발생 전후 특정 시간 범위의 API 서버 로그를 확인한 결과, 해당 구간에서 다수의 `HTTP 500` 응답이 발생한 것을 확인하였다. 이는 서버가 정상적인 요청을 처리하지 못한 상태였음을 의미한다.

본 장애는 서버 측 오류로 인해 발생하였으며,클라이언트 재시도 여부와 관계없이 사용자 또는 외부 시스템 입장에서는 서비스 신뢰성 저하로 인식될 수 있는 장애로 분류된다.

#### 2.4.4.2 SLO 영향

본 장애는 사전에 정의한 SLO 중 **Availability SLO** 및 **Error Rate SLI**에 영향을 미쳤다.
(참고: [2.3 SLI/SLO 설계](#23-slislo-설계))

![grafana](/images/rep4-2443-grafanaerrorrate.png)

- **Availability SLO**

  - 장애 지속 시간 동안 성공 요청 비율(Success Rate)이 감소하여, **Availability SLO 위반 또는 위반에 근접한 상태**로 평가될 수 있다.

- **Error Budget 소모 발생**

  - Error Rate(5xx)가 0.6이상으로 상승한 구간이 관측되었으며, Availability. 정의(1 - error Rate)에 따라 성공 성공 요청 비율은 40% 이하로 급격히 감소한 상태로 해벅할 수 있다.
  
  앞서 정의한 Availability SLO는 Success Rate를 기준으로 하며
  (참고: [2.3.4 SLO definitions](#234-slo-definitions),
  [2.3.5 SLO 요약 표](#235-slo-요약-표)),
  Availability는 Error Rate의 보완 지표로 해석된다.

종합적으로, 본 장애는 시전에 정의한 **Availability SLI및 Error Rate SLI 모두에 영향을 미친 장애**이다. 장애 구간 동안 `HTTP 5xx` 응답이 지속적으로 발생함에 따라 성공 요청 비율이 감소하였고, 이는 Availability SLO 위반 또는 위반에 근접한 상태로 평가될 수 있다.

또한 Error Rate 증가로 인해 `Error Budget이 일부 소모`되었으며, 이는 단일 장애 이벤트 자체보다는 **SLO 평가 기간(Rolling window) 내에서의 누적 신뢰성 지표 관점**에서 판단 되었다.

본 장애는 사용자 경험에 직접적인 영향을 주는 **신뢰성 관점의 장애(Reliability-impacting incident)**로 분류 된다.

#### 2.4.5 대응 (Response)

#### 2.4.5.1 초기 대응

Alert 발생 이후, 즉각적인 조치에 앞서
**서비스 상태 및 장애 범위를 우선적으로 확인** 하였다.

초기 대응 단계에서는 다음 항목을 중심으로 상황을 파악하였다.

- Grafana Dashboard를 통해 Error Rate (5xx) 및 전체 요청 상태 확인
- 장애가 단일 Endpoint에 국한된 문제인지, 서비스 전반에 영향을 주는지 확인
- 오류가 일시적인 스파이크인지, 지속적으로 발생하는지 여부 확인

이 단계에서는 즉각적인 수정이나 재기동보다, **정확한 상황 인지를 우선**하여 불필요한 조치나 오판을 방지하는 데 중점을 두었다.

#### 2.4.5.2 조치 내용

장애 원인이 의도적으로 주입된 오류임을 확인한 이후, 다음과 같은 조치를 수행하였다.

- 장애유도 로직 확인
- 의도적 장애 주입 중단
  - `/error` Endpoint 호출 중단
  - 또는 API 서비스 재시작을 통한 정상 상태 복구

조치는 서비스의 정상 동작을 회복시키는 데 필요한 **최소한의 범위로 제한하여** 수행하였다.

#### 2.4.5.3 대응 방식

- 대응 유형: 수동 대응
- 대응 기준: Runbook 기반의 표준 점검 절차 수행

본 대응은 자동 복구가 아닌, **Incident Response 흐름 검증을 위한 수동 개입**으로 수행되었다.

모든 대응 과정은 원인 분석과 재발 방지를 목적으로 하였으며, 개인 또는 특정 구성 요소에 책임을 전가하지 않는 **Blame-free 원칙**을 유지하였다.

대응 과정 전반에서는 다음 원칙을 유지하였다.

- 원인 분석과 재발 방지를 목적으로 한 대응
- 개인 또는 특정 구성 요소에 책임을 전가하지 않는 **Blame-free** 원칙 준수

본 대응 과정은 문제 해결과 학습을 목적으로 하며, 책임 추궁이 아닌 **시스템 개선 관점에서 수행**되었다.

#### 2.4.6 복구 (Recovery)

#### 2.4.6.1 복구 시점

장애 유도 중단 이후 API 서비스의 정상 응답이 확인 되었고, 이에 따라 Alert 상태가 정상적으로 해제되었다.

- 장애 유도 중단 후 정상 응답 확인
- Alert 상태 전이: 'firing → Resolved'

이는 Error Rate SLI가 정의된 정상 범위로 복귀했음을 의미한다.

#### 2.4.6.2 회복 지표

복구 여부는 개별 요청의 성공 여부가 아니라, **사전에 정의한 SLI/SLO 기준**을 통해 판단하였다.

- **Error Rate SLI**: 정상 범위 복귀
- **Availability 지표**: 안정화

해당 지표들은 Grafana Dashboard 및 Prometheus 데이터를 통해 확인 되었다.

> 서비스는 정의된 **SLO 기준 내의 정상 상태로 복구** 되었다.

#### 2.4.7 Lessons Learned

#### 2.4.7.1 잘 된 점

- **Error Rate** 기반 **Alert**가 Availability SLO 위반 징후를 조기에 감지함
- 장애 발생 → 감지 → 대응 → 복구까지의 **Incident Response 흐름이 명확하게 검증됨**
- 장애 영향 및 복구 여부를 **SLI/SLO를 기준으로 일관되게 판단**할 수 있었음

본 실험을 통해 Alert가 단순한 알림이 아니라, **서비스 신뢰성을 보호하기 위한 운영 도구**로 기능함을 확인.

#### 2.4.7.2 개선 할 점

- 단일 지표(Error Rate) 기반 **Alert은 상황에 따라 noise를 유발할 수 있음**
- Alert 조건이 SLI중심으로 구성되어 있어, **SLO 관점에서의 장기적 신뢰성 판단에는 한계**가 존재함

이에 따라 향후에는 다음과 같은 개선 여지가 있다.

- **SLO기반 Alert** 도입
- **Multi-window/ Multi-burn-rate Alert**를 통한 false positive 감소

#### 2.4.7.3 향후 계획

- **Latency(p95)** 기반 장애 시나리오를 추가하여 응답 지연이 사용자 경험에 미치는 영향을 추가적으로 검증
- Incident Response 과정에서 반복적으로 수행되는 절차를 **Runbook 형태로 문서화** 및 확장

이를 통해 단일 장애 대응을 넘어, **지속 가능한 신뢰성 운영 체계로 확장**하는 것을 목표로 한다.

### 2.5. RCA (Root Cause Analysis)

---

#### 2.5.1 장애 요약

본 Incident는 API 서비스에서 HTTP `5xx` 오류가 지속적으로 발생한 상황을 **의도적으로 재현**한 실험이다.장애는 FastAPI 서비스의 `/error` Endpoint를 반복 호출함으로써 서버 측 오류 트래픽을 유지하는 방식으로 유도되었으며, 그 결과 **`Error Rate (5xx)` SLI가 급격히 상승**하였다.

이로 인해 `Availability` 관점의 **`Success Rate`가 감소**했으며, 일부 구간에서는 **SLO 위반 또는 Error Budget 소모가 발생한 상태로 평가될 수 있는 상황**이 관측되었다.

본 Incident의 목적은 장애 자체가 아니라, **SLI/SLO 기반 Alert → Response → Recovery 흐름이 운영 환경과 유사하게 동작하는지**를 검증하는 데 있다.

#### 2.5.2 영향 범위

- **사용자 영향**
  - 일부 API 요청이 HTTP `500` 응답으로 실패
  - 정상 응답을 기대하는 클라이언트 요청이 처리되지 않음
  - HTTP `500` 응답 특성상, 클라이언트 또는 사용자 관점에서 요청 실패가 즉시 인지 가능한 장애로 인식됨

  → 본 장애는 클라이언트 네트워크 문제나 사용자 입력 오류가 아닌, **서버 측 처리 실패(Server-side failure)**로 분류된다.

- **SLO 영향**
  - **Availability SLO**
    - `Success Rate` 감소로 인해 SLO 위반 또는 위반에 근접한 상태로 평가됨

  - **Error Rate SLI**
    - HTTP `5xx` 비율이 임계치(5%)를 초과하는 상태가 일정 시간 지속됨

  - **Error Budget**
    - Rolling `30d` 기준 Availability SLO의 Error Budget 일부 소모

- **비영향 범위**
  - 데이터 손실 없음
  - 인프라 리소스 고갈 없음
  - 비정상 프로세스 종료 없음

  본 Incident는 단일 이벤트 자체보다는, SLO 평가 기간 내에서 신뢰성 지표가 어떻게 악화되는지를 보여주는 사례로 해석된다.

#### 2.5.3 타임라인 (Timeline)

| 단계 | 내용 |
| ------ | ------ |
| 장애 발생 | `/error` endpoint 반복 호출을 통해 HTTP 500 응답 지속 발생 |
| 지표 변화 | `Error Rate (5xx)` SLI 상승, `Success Rate` 감소 |
| 감지 | Prometheus가 `5분` 슬라이딩 윈도우 기준으로 Error Rate SLI 평가 |
| Pending | 임계치 초과 상태가 지속되며 Alert가 `Pending` 상태로 전이 |
| Firing | `for: 2m` 조건 충족 후 `HighErrorRate`가 `Firing` 상태로 전이 |
| 대응 | Grafana 대시보드 및 로그를 통해 장애 범위 확인 |
| 조치 | 장애 유도 중단 (`/error` 호출 중지 또는 API 재시작) |
| 복구 | Error Rate 정상화, Alert 상태가 `Resolved`로 전이 |

Alert 감지까지의 지연은 Alert Rule에 정의된 'for' 조건에 따른 **의도된 동작**이다.
이는 일시적인 오류로 인한 불필요한 Alert를 줄이고(Noise 감소), **Availability SLO 보호를 위한 신뢰성 신호만 경고**하기 위한 설계다.

#### 2.5.4 Root Cause

- **직접 원인 (Direct Cause)**
  - `/error` Endpoint가 항상 HTTP `500`을 반환하도록 설계됨
  - 해당 Endpoint에 대한 반복 호출로 인해 서버 오류 트래픽이 지속적으로 발생

- **근본 원인 (Root Cause)**
  - **Controlled Failure Injection** 시나리오에서,
  - Error Rate SLI를 기준으로 한 Alert 조건을 충족할 만큼의 오류 트래픽이 유지됨

  이는 코드 결함이나 인프라 장애가 아니라, **신뢰성 검증 목적의 통제된 장애 주입** 결과이다.

#### 2.5.5 재발 방지 대책

- **단기 개선**
  - 장애 유도용 Endpoint(`/error`)는 실험 환경에서만 활성화
  - 실험 종료 후 즉시 비활성화 또는 접근 제한(예: 인증 적용/ IP allowlist)
  - Runbook에 “의도적 장애 주입 여부 확인” 단계 명시

- **중·장기 개선**
  - **SLO 기반 Alert 도입**
    - 단일 임계치 기반(Error Rate threshold) Alert 대신 Error Budget 소모 속도 기반 Alert 설계
  - **Multi-window / Multi-burn-rate Alert**
    - 단기 스파이크와 지속 장애를 구분하여 Alert noise 감소
  - **Latency 기반 장애 시나리오 추가**
    - `p95 latency` 상승이 사용자 경험에 미치는 영향 검증
  - **Incident 대응 절차 Runbook화**
    - 감지 → 판단 → 대응 → 복구 단계를 명문화하여 재현성 확보
