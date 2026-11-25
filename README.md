# stock-data

KOSPI 30종목 + KOSDAQ 10종목의 일별 시세를 매일 갱신하는 저장소입니다.

## 데이터 기준 (2026-11-25부터)

| 항목 | 기준 |
| --- | --- |
| 시가·고가·저가·종가 | **KRX 정규장(09:00~15:30) 기준** — 15:30 종가단일가에서 확정된 공식 종가 |
| 거래량 | 정규장 + 시간외 + 애프터마켓(16:00~20:00) 합산 — KRX 공식 정의 |
| 등락률(Change) | 전 거래일 정규장 종가 대비 (소수 비율, 예: 0.0670 = +6.70%) |
| 수집 소스 | Yahoo Finance 일봉 (`.KS` / `.KQ`) |
| 기간 | 2024-12-01 ~ |

### 왜 Yahoo인가

2026-09-14 KRX 애프터마켓(16:00~20:00) 도입 이후 네이버·다음 등 포털의 일봉 '종가'는
당일 20:00 애프터마켓 최종 체결가로 표시됩니다. KRX 공식 정의는 시가·고가·저가·종가가
정규시장(15:30) 기준이고 거래량만 애프터마켓까지 합산한 값입니다(KRX Data Marketplace
전종목 시세 주석, KRX Open API FAQ 동일).

Yahoo Finance의 한국 종목 일봉은 이 KRX 공식 정의와 같게 내려옵니다. KRX 정보데이터시스템과
KRX Open API는 로그인·인증키가 필요하고 당일 데이터는 익일 오전 8시 이후에만 열려서,
로그인 없이 GitHub Actions에서 당일 마감 직후 값을 받을 수 있는 소스로 Yahoo를 씁니다.

### 참고

- Yahoo에 결측(빈 봉)으로 들어온 **2026-09-14 이전** 거래일은 네이버 일봉으로 보완합니다.
  그 이전에는 네이버 종가도 정규장 종가와 같기 때문입니다(현재 해당: 2025-09-19).
- 수정주가 기준이 소스마다 조금 달라, 과거 값이 이전(네이버 기준) 파일과 소폭 다를 수 있습니다
  (삼성바이오로직스·에코프로비엠 등 기업행위가 있던 종목).
- 장 마감(15:30) 전에 실행하면 당일 봉은 확정 전이므로 쓰지 않습니다.

## 산출물

- `data/Kospi/{코드}_{종목명}.csv` — `Date,Open,High,Low,Close,Volume,Change`
- `data/Kosdaq/{코드}_{종목명}.csv` — 동일
- `data/market_long.csv` — `Date,Market,Ticker,Name,Open,High,Low,Close,Volume,Change`

## 실행

```bash
pip install finance-datareader requests pandas openpyxl
python update_kp30kd10.py
```

`kospi_list.xlsx` / `kosdaq_list.xlsx`의 `Code`, `Name` 열을 읽어 종목을 정합니다.
