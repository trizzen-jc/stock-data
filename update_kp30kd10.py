import FinanceDataReader as fdr
import pandas as pd
import os
from datetime import datetime

# ====================== 설정 ======================
SAVE_DIR = 'data'          # Google Drive
KOSPI_DIR = os.path.join(SAVE_DIR, 'Kospi')
KOSDAQ_DIR = os.path.join(SAVE_DIR, 'Kosdaq')
START_DATE = '2024-12-01'
# =================================================

os.makedirs(KOSPI_DIR, exist_ok=True)
os.makedirs(KOSDAQ_DIR, exist_ok=True)

def download_stocks(list_file, save_dir, market_name):
    if not os.path.exists(list_file):
        print(f'{list_file} 파일이 없습니다.')
        return []

    df_list = pd.read_excel(list_file, dtype={'Code': str})
    print(f'\n[{market_name}] {len(df_list)}개 종목 다운로드 시작...')
    
    data_list = []
    
    for i, row in df_list.iterrows():
        code = str(row['Code']).zfill(6)
        name = str(row['Name'])
        
        try:
            df = fdr.DataReader(code, START_DATE)
            
            safe_name = name.replace('/', '_').replace('\\', '_').replace('*', '').replace('?', '')
            file_path = os.path.join(save_dir, f'{code}_{safe_name}.csv')
            
            df.to_csv(file_path, encoding='utf-8-sig')
            
            df_temp = df.reset_index()
            df_temp['Ticker'] = code
            df_temp['Name'] = name
            df_temp['Market'] = market_name
            data_list.append(df_temp)
            
            print(f'  ({i+1:2d}/{len(df_list)}) {name} ({code}) → 저장 완료')
            
        except Exception as e:
            print(f'  ({i+1:2d}/{len(df_list)}) {name} ({code}) 실패: {e}')
    
    return data_list

print(f'실행 시작: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
print(f'저장 위치: {SAVE_DIR}')

# 리스트 파일도 Google Drive에 있다고 가정
kospi_list = os.path.join(SAVE_DIR, 'kospi_list.xlsx')
kosdaq_list = os.path.join(SAVE_DIR, 'kosdaq_list.xlsx')

# 코스피 다운로드
kospi_data = download_stocks(kospi_list, KOSPI_DIR, 'KOSPI')

# 코스닥 다운로드
kosdaq_data = download_stocks(kosdaq_list, KOSDAQ_DIR, 'KOSDAQ')

# Long Format 통합 저장
all_data = kospi_data + kosdaq_data

if all_data:
    df_long = pd.concat(all_data, ignore_index=True)
    cols = ['Date', 'Market', 'Ticker', 'Name', 'Open', 'High', 'Low', 'Close', 'Volume', 'Change']
    df_long = df_long[[c for c in cols if c in df_long.columns]]
    
    long_path = os.path.join(SAVE_DIR, 'market_long.csv')
    df_long.to_csv(long_path, index=False, encoding='utf-8-sig')
    print(f'\nLong Format 저장 완료 → {long_path}')
    print(f'총 데이터 수: {len(df_long):,}행')

print('\n✅ 전체 작업 완료!')
print(f'코스피 폴더: {KOSPI_DIR}')
print(f'코스닥 폴더: {KOSDAQ_DIR}')
