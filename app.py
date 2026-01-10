import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from io import StringIO
import re
import time
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib import font_manager, rc
import platform
import warnings

# ---------------------------------------------------------
# [기능 추가] 비밀번호 체크 함수
# ---------------------------------------------------------
def check_password():
    """비밀번호가 맞는지 확인하는 함수"""
    # 세션 상태에 인증 여부 변수가 없으면 초기화
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    # 이미 로그인에 성공했으면 True 반환 (통과)
    if st.session_state["authenticated"]:
        return True

    # 로그인 안 된 상태면 비밀번호 입력창 띄우기
    st.title("🔒 가족 전용 주식 비서")
    st.write("부모님을 위한 공간입니다. 비밀번호를 입력해주세요.")
    
    password = st.text_input("비밀번호", type="password")
    
    if st.button("로그인"):
        # 🔐 금고(secrets)에서 비밀번호를 꺼내옵니다
        if password == st.secrets["FAMILY_PASSWORD"]:  
            st.session_state["authenticated"] = True
            st.rerun()  # 화면을 새로고침해서 내용을 보여줌
        else:
            st.error("비밀번호가 틀렸습니다.")
    
    return False

# ---------------------------------------------------------
# [설정] 페이지 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="저평가 주식 찾기", page_icon="💎", layout="wide")

# 🛑 [핵심] 비밀번호를 확인합니다. 통과 못하면 여기서 멈춥니다!
if not check_password():
    st.stop()

# =========================================================
# 👇 여기서부터는 보내주신 기존 코드 그대로입니다 (로그인 성공 시 실행)
# =========================================================

# ---------------------------------------------------------
# [설정] 투자 지표 필터링 조건 (기존 유지)
# ---------------------------------------------------------
CFG = {
    'MIN_CAP': 400000000000,   
    'MIN_AMT': 300000000,      
    'MAX_PBR': 1.0,            
    'MAX_PER': 10.0,           
    'MIN_ROE': 10.0,           
    'MIN_OP': 0,               
    'MIN_FOREIGN': 10.0,       
    'MAX_DEBT': 200.0,         
    'EXCLUDE': '은행|HDC현대산업개발|페인트|코리안리|지주|홀딩스|금융|증권|카드|공사|한국전력|한전KPS|강원랜드|자산|보험|레저|스팩|리츠|생명|해상'
}

# 요청하신 제목 수정
st.title("💎 저평가 주식")
st.markdown("##### 재무 상태가 튼튼한 종목 분석기")
st.markdown("---")

# ---------------------------------------------------------
# [함수 1] 데이터 수집 로직 (기존 유지)
# ---------------------------------------------------------
@st.cache_data
def get_naver_market_data():
    status_text = st.empty()
    status_text.info("⏳ 전체 주식 데이터를 훑어보고 있습니다... (잠시만 기다려주세요)")
    
    session = requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    url_submit = "https://finance.naver.com/sise/field_submit.naver"
    form_data = {
        'menu': 'market_sum',
        'returnUrl': 'http://finance.naver.com/sise/sise_market_sum.naver',
        'fieldIds': ['quant', 'amount', 'market_sum', 'per', 'roe', 'pbr', 'dividend_yield', 'operating_profit', 'frgn_rate']
    }
    session.post(url_submit, data=form_data, headers=headers)
    
    base_url = "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={}"
    total_df = pd.DataFrame()
    progress_bar = st.progress(0)
    
    for page in range(1, 45):
        progress_bar.progress(page / 45)
        try:
            res = session.get(base_url.format(page), headers=headers)
            html_table = StringIO(res.content.decode('euc-kr', 'replace'))
            dfs = pd.read_html(html_table, header=0)
            
            if len(dfs) < 2: break
            df = dfs[1]
            if df.dropna(how='all').empty: break
            
            soup = BeautifulSoup(res.text, 'html.parser')
            links = soup.select('table.type_2 tr td a.tltle')
            codes = [link['href'].split('=')[-1] for link in links]
            
            df = df[df['종목명'].notnull()].copy()
            if len(df) != len(codes): continue
            
            df['Ticker'] = codes
            total_df = pd.concat([total_df, df])
        except: break

    progress_bar.empty()
    status_text.empty() # 문구 지우기

    if total_df.empty: return pd.DataFrame()

    total_df = total_df.set_index('Ticker')
    cols_map = {
        '종목명': 'Name', '현재가': '종가', '전일비': '전일비', '등락률': '등락률',
        '시가총액': '시가총액', '거래량': '거래량', '거래대금': '거래대금',
        'PER': 'PER', 'ROE': 'ROE', 'PBR': 'PBR', '배당수익률': 'DIV',
        '영업이익': '영업이익', '외국인비율': '외국인비율'
    }
    current_cols = [c for c in cols_map.keys() if c in total_df.columns]
    df_final = total_df[current_cols].rename(columns=cols_map)
    
    def parse_change(value):
        if pd.isna(value): return 0
        s_val = str(value).strip().replace(',', '')
        try: return float(re.sub(r'[^0-9.-]', '', s_val))
        except: return 0.0

    df_final['전일비'] = df_final['전일비'].apply(parse_change)
    numeric_cols = ['종가', '시가총액', '거래량', '거래대금', 'PER', 'ROE', 'PBR', 'DIV', '영업이익', '외국인비율']
    for col in numeric_cols:
        if col in df_final.columns:
            df_final[col] = pd.to_numeric(df_final[col], errors='coerce').fillna(0)
            
    df_final['시가총액'] *= 100000000 
    df_final['거래대금'] *= 1000000
    df_final['영업이익'] *= 100000000
    
    return df_final

def add_debt_ratio(candidate_df):
    if candidate_df.empty: return candidate_df
    debt_ratios = []
    
    st.info("🔎 튼튼한 회사인지 재무제표를 꼼꼼히 살피고 있어요...")
    my_bar = st.progress(0)
    
    for i, ticker in enumerate(candidate_df.index):
        my_bar.progress((i + 1) / len(candidate_df))
        try:
            url = f"https://finance.naver.com/item/main.naver?code={ticker}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            dfs = pd.read_html(StringIO(res.text))
            
            found = False
            for df in dfs:
                if df.shape[1] > 1 and '부채비율' in df.iloc[:, 0].astype(str).values:
                    row = df[df.iloc[:, 0] == '부채비율'].iloc[0]
                    vals = pd.to_numeric(row[1:], errors='coerce').dropna()
                    if not vals.empty:
                        debt_ratios.append(vals.iloc[-1])
                        found = True
                        break
            if not found: debt_ratios.append(9999.0)
            time.sleep(0.05) 
        except: debt_ratios.append(9999.0)

    my_bar.empty()
    candidate_df['부채비율'] = debt_ratios
    return candidate_df

@st.cache_data
def get_detailed_daily_data(ticker, days=1825):
    url_sise = "https://finance.naver.com/item/sise_day.naver"
    price_list = []
    target_date = datetime.now() - timedelta(days=days)
    page = 1
    
    while True:
        try:
            res = requests.get(url_sise, headers={'User-Agent': 'Mozilla/5.0'}, params={'code': ticker, 'page': page})
            dfs = pd.read_html(StringIO(res.text))
            if len(dfs) < 1: break
            df = dfs[0].dropna()
            if df.empty: break
            
            stop_flag = False
            for _, row in df.iterrows():
                dt = datetime.strptime(row['날짜'], "%Y.%m.%d")
                if dt < target_date:
                    stop_flag = True; break
                price_list.append({'Date': dt, 'Close': int(row['종가'])})
            
            if stop_flag or page > 400: break
            page += 1
            time.sleep(0.02)
        except: break
            
    df_price = pd.DataFrame(price_list)
    if not df_price.empty:
        df_price = df_price.set_index('Date').sort_index()
    return df_price

# =========================================================
# [메인 화면 구성]
# =========================================================

# 사이드바 설정
st.sidebar.header("메뉴")
st.sidebar.write("아래 버튼을 눌러주세요.")

# [수정됨] 버튼 이름과 아이콘 변경
if st.sidebar.button("🔍 찾기"):
    df_all = get_naver_market_data()

    cond_cap = df_all['시가총액'] >= CFG['MIN_CAP']
    cond_amt = df_all['거래대금'] >= CFG['MIN_AMT']
    cond_pbr = (df_all['PBR'] <= CFG['MAX_PBR']) & (df_all['PBR'] > 0)
    cond_per = (df_all['PER'] <= CFG['MAX_PER']) & (df_all['PER'] > 0)
    cond_roe = df_all['ROE'] >= CFG['MIN_ROE']
    cond_op = df_all['영업이익'] > CFG['MIN_OP']
    cond_frgn = df_all['외국인비율'] >= CFG['MIN_FOREIGN']
    cond_nm = ~df_all['Name'].str.contains(CFG['EXCLUDE'])

    df_candidates = df_all[cond_cap & cond_amt & cond_pbr & cond_per & cond_roe & cond_op & cond_frgn & cond_nm].copy()
    
    if not df_candidates.empty:
        df_candidates = add_debt_ratio(df_candidates)
        cond_debt = df_candidates['부채비율'] <= CFG['MAX_DEBT']
        df_final = df_candidates[cond_debt].copy().sort_values(by='시가총액', ascending=False)
        
        st.session_state['result'] = df_final
        st.toast(f"분석 완료! {len(df_final)}개 종목 발견!", icon="🎉") # 알림 메시지 추가
    else:
        st.warning("조건을 만족하는 종목이 없습니다.")

# [개선] 초기 화면 안내 메시지 (데이터 없을 때)
if 'result' not in st.session_state:
    st.info("👈 **왼쪽 사이드바의 '찾기' 버튼**을 누르면 분석이 시작됩니다.")
    st.write("이 프로그램은 시가총액, 영업이익, 부채비율 등 8가지 지표를 분석해 싸고 튼튼한 기업을 찾아줍니다.")

# [결과 화면]
if 'result' in st.session_state:
    df_final = st.session_state['result']
    
    st.success(f"**총 {len(df_final)}개의 종목**을 찾았습니다!")
    st.dataframe(df_final)

    st.markdown("---")
    st.subheader("📈 차트 분석")
    st.caption("종목을 선택하면 5년치 주가 흐름을 보여줍니다.")
    
    ticker_list = [f"{row['Name']} ({ticker})" for ticker, row in df_final.iterrows()]
    selected = st.selectbox("종목 선택:", ticker_list)
    
    if selected:
        code = selected.split('(')[-1].replace(')', '')
        name = selected.split(' (')[0]
        
        if st.button("차트 보기"):
            with st.spinner(f"'{name}'의 과거 데이터를 가져오는 중..."):
                df_daily = get_detailed_daily_data(code)
                
                if not df_daily.empty:
                    if platform.system() == 'Windows':
                        font_path = "c:/Windows/Fonts/malgun.ttf"
                        font_name = font_manager.FontProperties(fname=font_path).get_name()
                        rc('font', family=font_name)
                    plt.rcParams['axes.unicode_minus'] = False 
                    
                    fig, ax = plt.subplots(figsize=(12, 6))
                    ax.plot(df_daily.index, df_daily['Close'], label='주가', color='black', alpha=0.6)
                    
                    # 이동평균선
                    ma120 = df_daily['Close'].rolling(window=120).mean()
                    ma240 = df_daily['Close'].rolling(window=240).mean()
                    ax.plot(df_daily.index, ma120, label='120일선 (6개월 평균)', color='green', linestyle='--', linewidth=2)
                    ax.plot(df_daily.index, ma240, label='240일선 (1년 평균)', color='red', linestyle='--', linewidth=2)
                    
                    ax.set_title(f"{name} (최근 5년)", fontsize=18, fontweight='bold')
                    ax.legend(fontsize=12)
                    ax.grid(True, alpha=0.3)
                    
                    st.pyplot(fig)
                    
                    # [개선] 차트 도움말 추가
                    st.markdown("""
                    **💡 차트 보는 팁**
                    * 초록색 점선(120일선)보다 주가가 위에 있으면 상승 추세일 가능성이 높습니다.
                    * 빨간색 점선(240일선)은 1년 평균 가격으로, 장기적인 바닥을 확인하는 데 도움이 됩니다.
                    """)
                else:

                    st.error("데이터가 없습니다.")


