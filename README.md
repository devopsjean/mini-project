# SRE mini Project

본 프로젝트는 SRE 관점에서

- 서비스 신뢰성 측정
- 관측 가능성(Observability) 구축
- 장애 유도 및 대응
- RCA 문서화

를 목표로 하는 미니프로젝트 입니다.

## 구조

![structure](images/structure.png)

## 2.요구사항

### 2.1. 서비스(API) - Verification

본 API는 신뢰성 테스트 목적의 서비스로, 정상 응답/ 의도적 지연/ 의도적 5xx 오류를 재현할 수 있다.

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

### 2.2. Obervability 스택

본 프로젝트는 Metrics 기반 관측 가능성(Observability)을 목표로 하며, 아래 구성으로 수집/시각화/알림을 구현합니다.

#### 2.2.1 Metrics: Prometheus

API는 /metrics에서 Prometheus 형식의 메트릭을 노출하며, Prometheus는 해당 엔드포인트를 scrape 하여 시계열 데이터로 저장한다.
본 프로젝트에서는 API의 요청 수/지연 시간/오류 응답 같은 신뢰성 지표(SLI 후보) 를 수집하기 위해 Prometheus를 사용합니다.

##### 2.2.1.1 API and prometheus metrics structure

![apiprometheusmetricstructure](/images/rep2-prometheus-metrics-structure.png)

Prometheus는 기본 scrape_interval(15s)에 따라 API의 /metrics 엔드포인트를 주기적으로 수집한다.
scrape_interval=15s는 데모 환경에서 메트릭 반응성을 확보하면서 과도한 scrape 부하를 피하기 위한 기본값으로 설정하였다.

##### 2.2.1.2 API 노출(expose)

![api-metrics](images/rep2-api-metrics.png)

사용자가 확인하는 URL은 http://localhost:8080/metrics 이며, Prometheus는 docker network 내부에서 http://api:8080/metrics 를 scrape 대상으로 사용한다.

##### 2.2.1.3 prometheus 수집(scrape)

![prometheus](images/rep2-prometheus-metrics.png)

사용자가 확인하는 URL은 http://localhost:9090/metrics 이며, Prometheus는 docker network 내부에서 http://prometheus:9090/metrics 를 scrape 하는 주체으로 사용한다.

##### 2.2.1.4 quary at prometheus graph

![quary](images/rep2-quary.png)

- http_requests_total: Counter (누적 요청 수)
- http_request_duration_seconds: Histogram (지연 시간 분포)

Counter는 누적 값으로 트래픽 추이를 확인하는 데 사용되며,Histogram은 p95/p99 지연 시간과 같은 SLO 계산의 기반이 된다.
해당 메트릭들은 이후 SLI/SLO 정의(가용성, 지연시간) 및 Alert Rule의 기반으로 사용된다.

#### 2.2.2 Visualization: Grafana

![visualization](images/rep2-visualizationgranafa.png)

본 구조에서는 API가 /metrics 엔드포인트를 통해 메트릭을 노출하고, Prometheus가 이를 주기적으로 수집하여 TSDB에 저장한다. Grafana는 Prometheus의 Query API에 PromQL 요청을 전달하며, Prometheus는 내부 TSDB에서 시계열 데이터를 조회한 뒤 PromQL 연산을 수행하고, 계산된 결과를 Grafan에 반환한다.

##### 2.2.2.1 Data Source

![datasources](images/rep2-datasources.png)

Granafa에서 Prometheus를 Data Source로 등록하였다.
Docker Compose 환경에서 서비스 간 통신을 위해 Prometheus의 내부 주소(http://prometheus:9090)을 사용하였으며, Data Source 연결 테스트를 통해 정상적으로 메트릭을 조회할 수 있음을 확인하였다.

##### 2.2.2.2 Dashboard and Panel 구성

1. **Traffic (RPS)**

    ![trafficrps](images/rep2-trafficrps.png)

    Traffic 패널은 API에 유입되는 요청량을 초당 요청수(RPS)기준으로 시각화 한다.
    요청량의 변화는 서비스 부하 상태를 판단하는 기본 관측 지표로 활용한다.

1. **Error Rate (5xx)**

    Error Rate 패널은 전체 요청 대비 HTTP 5xx 응답 비율을 나타낸다.
    서버 오류는 사용자 경험에 직접적인 영향을 미치므로 핵심 관측 지표로 설정하였다.

    ```query
    sum(rate(http_requests_total{status=~"5.."}[5m]))
    /
    sum(rate(http_requests_total[5m]))
    ```

    현재 환경에서는 HTTP 5xx응답이 발생하지 않아 에러율은 0에 수렴하는 값을 보인다. 이는 서비스가 정상 상태임을 의미하며, 장애 발생시 해당 패널을 통해 즉각적인 이상탐지가 가능하다.

    ![errorrate](images/rep2-errorrate.png)

1. **Latency (p95)**

    평균 지연시간은 일부 느린 요청을 가릴 수 있으므로, 히스토그램 기반 p95 지연시간을 사용하여 상위 지연 요청을 기준으로 서비스 응답성을 관측하였다.

    ```query
    histogram_quantile(
    0.95,
    sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
    ```

    - API 요청 시 p95 지연시간이 시간 흐름에 따라 변화
    - Histogram 기반 metric이 정상적으로 집게됨을 확인

    ![latencyp95](images/rep2-latencyp95.png)

1. **결과 요약**

    ![granafadashboard](/images/rep2-granafadashboard.png)

    위 구성을 통해 API서비스에 대한 트래픽, 오류, 지연시간을 Grafana 대시보드에서 통합적으로 관측할 수 있음을 확인하였다. 이는 Prometheus 기반 메트릭 수집과 Grafana 시각화가 정상적으로 연동되었음을 의미하며, 서비스 상태를 실시가으로 파악할 수 있는 기본적인 Observavility 환경을 구축하였다.

#### 2.2.3 Alerting: Prometheus Alert Rule 또는 Grafana Alert

### 2.3. SLI/SLO 설계

#### 2.3.1. SLI 정의( 최소 3개 이상)

#### 2.3.2. SLO 정의( 정량적인 목표)

- 30일 기준 Availability
- p95 Latencty 300ms 이하

### 2.4. 장애 시나리오 및 Incident Response

- API서버를 활용해 의도적으로 장애를 발생
- Alert가 정적으로 동작하는 것을 확인
- 장애 발생부터 복구까지의 흐름을 문서로 정리

### 2.5. RCA (Root Cause Analysis)

- 장애 요약
- 영향 범위
- 타임라인 (발생 -> 감지 -> 대응 복구)
- Root Cause
- 재발 방지 대책

## Project Context (for AI assistants)

- This is an SRE mini project using docker-compose
- Prometheus and Grafana are already running with provisioning
- API is FastAPI exposing /health and /metrics
- Current issue: API container not listening on port 8080
