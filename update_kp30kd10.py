"""
KOSPI/KOSDAQ 40종목 일별 시세 수집 (KRX 정규장 종가 기준)

■ 왜 Yahoo 소스인가
2026-09-14 KRX 애프터마켓(16:00~20:00) 도입 이후, 네이버·다음 등 포털의 일봉 '종가'는
당일 20:00 애프터마켓 최종 체결가로 표시된다. 반면 KRX 공식 일별 데이터의 정의는
  - 시가/고가/저가/종가 : 정규시장(09:00~15:30) 기준
  - 거래량/거래대금     : 정규시장 + 시간외 + 애프터마켓 합산
이다(KRX Data Marketplace 전종목 시세 주석, KRX Open API FAQ 동일).
Yahoo Finance의 한국 종목 일봉은 이 KRX 공식 정의와 동일하게 내려온다
(정규장 OHLC + 합산 거래량). KRX 정보데이터시스템/Open API는 로그인·인증키가
필요하고 당일 데이터는 익일 오전 8시 이후에만 제공되므로, 로그인 없이 GitHub
Actions에서 당일 마감 직후 값을 받을 수 있는 소스로 Yahoo를 사용한다.

■ 산출물 (기존 포맷 유지)
  data/Kospi/{code}_{name}.csv   : Date,Open,High,Low,Close,Volume,Change
  data/Kosdaq/{code}_{name}.csv  : 동일
  data/market_long.csv           : Date,Market,Ticker,Name,Open,High,Low,Close,Volume,Change
"""

import os
import time
from datetime import datetime, timedelta, timezone

import FinanceDataReader as fdr
import pandas as pd
import requests

# ====================== 설정 ======================
SAVE_DIR = 'data'
KOSPI_DIR = os.path.join(SAVE_DIR, 'Kospi')
KOSDAQ_DIR = os.path.join(SAVE_DIR, 'Kosdaq')
START_DATE = '2024-12-01'

YAHOO_CHART_URL = 'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}'
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
    'Accept': 'application/json,text/plain,*/*',
}
MAX_RETRIES = 5
SLEEP_BETWEEN_TICKERS = 0.7      # Yahoo 호출 간 간격(초)
MIN_ROWS = 300                   # 비정상적으로 짧은 응답 차단(약 1년치 이상)
KST = timezone(timedelta(hours=9))
# 2026-09-14 KRX 애프터마켓 개설일. 이 날짜 이전은 네이버 일봉도 정규장 종가와 같으므로
# Yahoo 쪽 결측일 보완에만 사용한다.
AFTERMARKET_START = '2026-09-14'
REGULAR_CLOSE_CUTOFF = (15, 35)  # 이 시각 이전에는 '당일' 봉을 확정값으로 쓰지 않음
# =================================================

os.makedirs(KOSPI_DIR, exist_ok=True)
os.makedirs(KOSDAQ_DIR, exist_ok=True)


def now_kst():
    return datetime.now(KST)


def yahoo_symbol(code, market_name):
    """KOSPI → {code}.KS, KOSDAQ → {code}.KQ"""
    suffix = '.KS' if market_name == 'KOSPI' else '.KQ'
    return f'{code}{suffix}'


def fetch_yahoo_daily(symbol, start_date):
    """Yahoo 일봉 수집. 실패 시 재시도하며, 실패하면 예외를 던진다."""
    start = datetime.combine(
        datetime.strptime(start_date, '%Y-%m-%d').date() - timedelta(days=10),  # 등락률 계산용 여유
        datetime.min.time()).replace(tzinfo=KST)
    end = now_kst() + timedelta(days=1)

    params = {
        'period1': int(start.timestamp()),
        'period2': int(end.timestamp()),
        'interval': '1d',
        'includeAdjustedClose': 'true',
        'events': 'div,splits',
    }

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(YAHOO_CHART_URL.format(symbol=symbol),
                                params=params, headers=HEADERS, timeout=30)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f'HTTP {resp.status_code}')
            resp.raise_for_status()
            payload = resp.json()
            result = (payload.get('chart') or {}).get('result')
            if not result:
                raise ValueError(f'empty chart result: {payload.get("chart", {}).get("error")}')
            result = result[0]
            timestamps = result.get('timestamp') or []
            quote = result['indicators']['quote'][0]
            if not timestamps:
                raise ValueError('no timestamps')

            index = (pd.to_datetime(timestamps, unit='s', utc=True)
                     .tz_convert('Asia/Seoul')
                     .normalize()
                     .tz_localize(None))
            df = pd.DataFrame({
                'Open': quote.get('open'),
                'High': quote.get('high'),
                'Low': quote.get('low'),
                'Close': quote.get('close'),
                'Volume': quote.get('volume'),
            }, index=index)
            df.index.name = 'Date'
            return df
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            wait = min(2 ** attempt, 20)
            print(f'    ! {symbol} 시도 {attempt}/{MAX_RETRIES} 실패: {exc} → {wait}초 후 재시도')
            time.sleep(wait)

    raise RuntimeError(f'{symbol} 수집 실패: {last_err}')


def fill_gap_days_from_naver(code, df):
    """Yahoo에 빠진 과거 거래일을 네이버 일봉으로 보완.

    보완 대상은 애프터마켓 도입(2026-09-14) 이전 날짜뿐이다. 그 이전에는 네이버 일봉의
    종가가 곧 정규장 종가이므로 값의 의미가 같다. 수정주가 기준이 소스마다 조금 다를 수
    있어, 가장 가까운 공통 거래일의 가격 비율로 눈금을 맞춰 넣는다.
    """
    try:
        ref = fdr.DataReader(code, START_DATE)
    except Exception as exc:  # noqa: BLE001
        print(f'    · {code} 네이버 대조 실패(건너뜀): {exc}')
        return df

    ref.index = pd.to_datetime(ref.index).normalize()
    ref = ref[~ref.index.duplicated(keep='last')]
    df = df.sort_index()

    def _is_missing(day):
        if day not in df.index:
            return True
        return pd.isna(df.at[day, 'Close'])

    missing = [d for d in ref.index
               if d < pd.Timestamp(AFTERMARKET_START) and d >= pd.Timestamp(START_DATE)
               and _is_missing(d)]
    if not missing:
        return df

    filled = []
    for d in missing:
        common = df.index.intersection(ref.index)
        common = common[[day != d and pd.notna(df.at[day, 'Close']) for day in common]]
        if len(common) == 0:
            continue
        nearest = common[common.get_indexer([d], method='nearest')[0]]
        ratio = float(df.at[nearest, 'Close']) / float(ref.at[nearest, 'Close'])
        row = ref.loc[d]
        filled.append((d, {
            'Open': round(float(row['Open']) * ratio),
            'High': round(float(row['High']) * ratio),
            'Low': round(float(row['Low']) * ratio),
            'Close': round(float(row['Close']) * ratio),
            'Volume': round(float(row['Volume']) / ratio) if ratio else row['Volume'],
        }))

    for d, values in filled:
        df.loc[d] = values
    df = df.sort_index()
    print(f'    · 네이버로 보완한 결측일: {[str(d.date()) for d, _ in filled]}')
    return df


def clean_frame(df):
    """정규장 기준 일봉으로 정리: 결측/중복 제거, 당일 미확정 봉 제외."""
    df = df[df['Close'].notna() & df['Open'].notna() & df['High'].notna() & df['Low'].notna()]
    df = df[~df.index.duplicated(keep='last')]
    df = df.sort_index()

    # 장 마감(15:30) 전이면 오늘 봉은 장중 스냅샷이므로 제외
    now = now_kst()
    if (now.hour, now.minute) < REGULAR_CLOSE_CUTOFF:
        df = df[df.index < pd.Timestamp(now.date())]

    for col in ('Open', 'High', 'Low', 'Close', 'Volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    df['Volume'] = df['Volume'].fillna(0)
    for col in ('Open', 'High', 'Low', 'Close'):
        df[col] = df[col].round().astype('int64')
    df['Volume'] = df['Volume'].round().astype('int64')

    # 등락률: 전 거래일 종가 대비 (여유분까지 포함해 계산한 뒤 시작일부터 자름)
    df['Change'] = df['Close'].pct_change()
    df = df[df.index >= pd.Timestamp(START_DATE)]
    return df


def read_existing(file_path):
    """이전에 저장된 CSV (수집 실패 시 대체용)."""
    if not os.path.exists(file_path):
        return None
    try:
        old = pd.read_csv(file_path, parse_dates=['Date'], index_col='Date')
        old = old.sort_index()
        if 'Change' not in old.columns:
            old['Change'] = old['Close'].pct_change()
        return old
    except Exception:  # noqa: BLE001
        return None


def download_stocks(list_file, save_dir, market_name):
    if not os.path.exists(list_file):
        print(f'{list_file} 파일이 없습니다.')
        return []

    df_list = pd.read_excel(list_file, dtype={'Code': str})
    print(f'\n[{market_name}] {len(df_list)}개 종목 수집 시작...')

    data_list = []

    for i, row in df_list.iterrows():
        code = str(row['Code']).zfill(6)
        name = str(row['Name'])
        safe_name = name.replace('/', '_').replace('\\', '_').replace('*', '').replace('?', '')
        file_path = os.path.join(save_dir, f'{code}_{safe_name}.csv')

        try:
            raw = fill_gap_days_from_naver(code, fetch_yahoo_daily(yahoo_symbol(code, market_name), START_DATE))
            df = clean_frame(raw)
            if len(df) < MIN_ROWS:
                raise ValueError(f'행 수 부족({len(df)}행) — 응답 이상')

            out = df.copy()
            out.index.name = 'Date'
            out.sort_index(ascending=False).to_csv(file_path, encoding='utf-8-sig')

            df_temp = out.reset_index()
            df_temp['Ticker'] = code
            df_temp['Name'] = name
            df_temp['Market'] = market_name
            data_list.append(df_temp)

            last = out.index.max().date()
            print(f'  ({i+1:2d}/{len(df_list)}) {name} ({code}) → {len(out)}행, 최종 {last} 종가 {int(out["Close"].iloc[-1]):,}')

        except Exception as e:  # noqa: BLE001
            print(f'  ({i+1:2d}/{len(df_list)}) {name} ({code}) 실패: {e}')
            old = read_existing(file_path)
            if old is not None and len(old) > 0:
                df_temp = old.reset_index()
                df_temp['Ticker'] = code
                df_temp['Name'] = name
                df_temp['Market'] = market_name
                data_list.append(df_temp)
                print(f'      → 기존 파일({len(old)}행)로 대체')

        time.sleep(SLEEP_BETWEEN_TICKERS)

    return data_list


print(f'실행 시작: {now_kst().strftime("%Y-%m-%d %H:%M:%S")} (KST)')
print('기준: KRX 정규장(15:30) 종가 · 거래량은 애프터마켓 합산(KRX 공식 정의)')

kospi_list = 'kospi_list.xlsx'
kosdaq_list = 'kosdaq_list.xlsx'

kospi_data = download_stocks(kospi_list, KOSPI_DIR, 'KOSPI')
kosdaq_data = download_stocks(kosdaq_list, KOSDAQ_DIR, 'KOSDAQ')

# Long Format 통합 저장
all_data = kospi_data + kosdaq_data

if all_data:
    df_long = pd.concat(all_data, ignore_index=True)
    cols = ['Date', 'Market', 'Ticker', 'Name', 'Open', 'High', 'Low', 'Close', 'Volume', 'Change']
    df_long = df_long[[c for c in cols if c in df_long.columns]]
    df_long['Date'] = pd.to_datetime(df_long['Date']).dt.strftime('%Y-%m-%d')

    long_path = os.path.join(SAVE_DIR, 'market_long.csv')
    df_long = df_long.sort_values(['Date', 'Market', 'Ticker'], ascending=[False, True, True])
    df_long.to_csv(long_path, index=False, encoding='utf-8-sig')
    print(f'\nLong Format 저장 완료 → {long_path}')
    print(f'총 데이터 수: {len(df_long):,}행')

print('\n✅ 전체 작업 완료!')
print(f'코스피 폴더: {KOSPI_DIR}')
print(f'코스닥 폴더: {KOSDAQ_DIR}')
