# 전략 정의 (StrategyDefinition YAML)

## 폴더 규칙

| 경로 | 커밋 여부 | 용도 |
|------|-----------|------|
| `research/strategies/*.yaml` | ✅ 공개 | generic 전략 (value_v1, ETF 로테이션 등) — 클론 직후 바로 동작 |
| `research/strategies/examples/` | ✅ 공개 | 구조 예제 (중립 가중치) |
| `research/strategies/private/` | ❌ **gitignore** | **개인 튜닝 전략** — 방정식 가중치 등 비공개 값 |

## 해석 순서

백엔드(`daily_analysis` 등)가 전략 이름으로 로드할 때 **`private/` → 공개 폴더**
순서로 찾습니다. 즉 `private/qlab_alpha_v2.yaml`이 있으면 공개 예제 대신
그 파일이 사용됩니다.

## 개인 전략 만들기

```bash
cp research/strategies/examples/qlab_alpha_v2.example.yaml \
   research/strategies/private/qlab_alpha_v2.yaml
# private/ 파일에서 groups 가중치를 직접 튜닝 (walk-forward 권장):
#   from research.backtest.walk_forward import walk_forward
#   walk_forward(strategy, optimize_trials=12)
```

기본 전략 이름은 `.env`의 `DEFAULT_STRATEGY_NAME` (기본 `value_v1`)로 바꿉니다.
자동매매 안전조건(킬스위치·주문한도·일일손실한도·mock 여부)은 전부 `.env`에서
관리합니다 — `.env.example` 참고.
