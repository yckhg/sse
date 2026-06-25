# tests/spec/mcp-tenant-data-access

`docs/spec/mcp-tenant-data-access.md` (Spec 1)의 검증 단언 A~L을 1:1로 강제하는
적합성(conformance) 테스트. 계약과 검증이 1:1로 마주본다.

- 각 테스트는 단언 ID로 명명한다 (`test_a_*`, `test_b_*`, …).
- **인프라 단언 (A,B,C,D,K)**: 라이브/리포 상태를 관측 → 지금 실행 가능.
- **행위 단언 (E,F,G,H,I,J,L)**: Spec 1의 보안 MCP 서버가 떠 있어야 판정 가능 →
  구현 전에는 `xfail(pending implementation)`. 구현 후 마킹을 풀면 합격 기준이 된다.

## 실행 (컨테이너 안에서, 호스트 설치 금지)

```bash
# python + pytest 컨테이너에서 (호스트엔 설치하지 않는다)
docker run --rm -v "$PWD":/w -w /w --network host python:3.11 \
  sh -c "pip install -q pytest && pytest tests/spec/mcp-tenant-data-access -v"
```

> 인프라 단언은 호스트 네트워크/도커 소켓 관측이 필요하므로 CI에서는 적절한 권한
> 컨텍스트에서 실행한다. 프로덕션 데이터에 대한 읽기는 read-only로만.

## 현재 baseline (구현 전)

| 단언 | 상태 | 근거 |
|------|------|------|
| A 공개 리스너 부재 | **NOK** | `0.0.0.0:8080`, `0.0.0.0:20007` 바인딩 존재 |
| B 게이트웨이 비노출 | **NOK** | gateway nginx에 20007 프록시 + 포트 매핑 존재 |
| C docker.sock 미마운트 | **NOK** | `sse-mcp-server`에 `/var/run/docker.sock` 마운트됨 |
| D 쓰기 도구 부재 | **NOK** | 라이브 MCP에 `execute`(쓰기) 도구 존재 |
| E~L | PENDING | 보안 MCP 구현 후 활성화 |
| K 시크릿 미노출 | n/a | 구현이 이 트랙에 들어오기 전 (구현 시 유지 필수) |
