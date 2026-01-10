import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from io import StringIO
import re
import time
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import plotly.express as px
import os

# ---------------------------------------------------------
# [설정] 페이지 기본 설정 (가장 위에 있어야 함)
# ---------------------------------------------------------
st.set_page_config(
    page_title="지인 전용 주식 비서", 
    page_icon="💎", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------
# [기능] 비밀번호 체크
# ---------------------------------------------------------
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if st.session_state["authenticated"]:
        return True

    # 로그인 화면 디자인 개선
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🔒 지인 전용 주식 비서")
        st.markdown("관계자 외 출입금지 구역입니다.")
        password = st.text_input("비밀번호를 입력하세요", type="password")
        
        if st.button("로그인", use_container_width=True):
            try:
                correct_password = st.secrets["FAMILY_PASSWORD"]
            except:
                correct_password = "1234" 

            if password == correct_password:  
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("비밀번호가 틀렸습니다.")
    return False

if not check_password():
    st.stop()

# ---------------------------------------------------------
# [함수] 데이터 수집 및 처리 (핵심 로직)
# ---------------------------------------------------------
@st.cache_data(ttl=3600) # 1시간 캐싱
def get_naver_market_data():
    # 진행 상황 표시 커스텀
    progress_text = "전체 시장 데이터를 스캔하고 있습니다... (약 1~2분 소요)"
    my_bar = st.progress(0, text=progress_text)
    
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
    
    for page in range(1, 45): # 코스피/코스닥 주요 종목 스캔
        percent_complete = page / 45
        my_bar.progress(percent_complete, text=f"{progress_text} ({int(percent_complete*100)}%)")
        
        try:
            res = session.get(base_url.format(page), headers=headers)
            html_table = StringIO(res.content.decode('euc-kr', 'replace'))
            dfs = pd.read_html(html_table, header=0)
            
            if len(dfs) < 2: break
            df = dfs[1]
            if df.dropna(how='all').empty: break
            
            # 종목코드 추출
            soup = BeautifulSoup(res.text, 'html.parser')
            links = soup.select('table.type_2 tr td a.tltle')
            codes = [link['href'].split('=')[-1] for link in links]
            
            df = df[df['종목명'].notnull()].copy()
            if len(df) != len(codes): continue
            
            df['Ticker'] = codes
            total_df = pd.concat([total_df, df])
        except: break

    my_bar.empty()
    
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
    
    # 데이터 전처리
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
            
    # 단위 보정 (원 단위로)
    df_final['시가총액'] *= 100000000 
    df_final['거래대금'] *= 1000000
    df_final['영업이익'] *= 100000000
    
    return df_final

def add_debt_ratio(candidate_df):
    if candidate_df.empty: return candidate_df
    debt_ratios = []
    
    progress_text = "재무제표(부채비율) 정밀 분석 중..."
    my_bar = st.progress(0, text=progress_text)
    
    for i, ticker in enumerate(candidate_df.index):
        my_bar.progress((i + 1) / len(candidate_df), text=f"{progress_text} ({candidate_df.iloc[i]['Name']})")
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
            time.sleep(0.02) 
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
            time.sleep(0.01)
        except: break
            
    df_price = pd.DataFrame(price_list)
    if not df_price.empty:
        df_price = df_price.set_index('Date').sort_index()
    return df_price

# =========================================================
# [UI - 사이드바] 검색 조건 설정 (완전한 웹사이트의 핵심)
# =========================================================
with st.sidebar:
    st.header("🔍 검색 필터 설정")
    st.markdown("원하는 조건으로 주식을 찾아보세요.")
    
    with st.expander("기본 조건 (Valuation)", expanded=True):
        in_max_per = st.slider("최대 PER (주가수익비율)", 0.0, 50.0, 10.0, step=0.5, help="낮을수록 저평가")
        in_max_pbr = st.slider("최대 PBR (주가순자산비율)", 0.0, 5.0, 1.0, step=0.1, help="1 미만이면 자산가치보다 쌈")
        in_min_roe = st.slider("최소 ROE (자기자본이익률)", 0.0, 30.0, 10.0, help="높을수록 돈을 잘 범")

    with st.expander("재무 안정성 & 수급", expanded=False):
        in_max_debt = st.slider("최대 부채비율 (%)", 0.0, 500.0, 200.0, step=10.0)
        in_min_foreign = st.slider("최소 외국인 지분율 (%)", 0.0, 50.0, 5.0, step=1.0)
        in_min_amt = st.number_input("최소 거래대금 (억원)", value=3, step=1) * 100000000

    with st.expander("제외할 업종/키워드", expanded=False):
        default_exclude = '은행|HDC현대산업개발|페인트|코리안리|지주|홀딩스|금융|증권|카드|공사|한국전력|한전KPS|강원랜드|자산|보험|레저|스팩|리츠|생명|해상'
        in_exclude = st.text_area("제외 키워드 ( '|' 로 구분)", value=default_exclude, height=100)

    st.markdown("---")
    # [분석 시작 버튼] 사이드바 하단 배치
    run_btn = st.button("🚀 조건에 맞는 종목 찾기", type="primary", use_container_width=True)
    st.caption("버튼을 누르면 분석이 시작됩니다.")

# =========================================================
# [메인 화면]
# =========================================================
st.title("💎 저평가 우량주 발굴기")
st.markdown(f"""
**설정된 조건:** PER **{in_max_per}**이하, PBR **{in_max_pbr}**이하, ROE **{in_min_roe}%**이상인 
싸고 튼튼한 기업을 찾습니다.
""")

# 세션 상태 초기화 (결과 저장용)
if 'result_df' not in st.session_state:
    st.session_state['result_df'] = pd.DataFrame()
if 'analysis_done' not in st.session_state:
    st.session_state['analysis_done'] = False

# [분석 로직 실행]
if run_btn:
    # 1. 전체 데이터 수집
    df_all = get_naver_market_data()

    # 2. 1차 필터링
    cond_cap = df_all['시가총액'] >= 400000000000 # 시총 4000억 이상 (고정)
    cond_amt = df_all['거래대금'] >= in_min_amt
    cond_pbr = (df_all['PBR'] <= in_max_pbr) & (df_all['PBR'] > 0)
    cond_per = (df_all['PER'] <= in_max_per) & (df_all['PER'] > 0)
    cond_roe = df_all['ROE'] >= in_min_roe
    cond_op = df_all['영업이익'] > 0 # 적자 기업 제외
    cond_frgn = df_all['외국인비율'] >= in_min_foreign
    cond_nm = ~df_all['Name'].str.contains(in_exclude)

    df_candidates = df_all[cond_cap & cond_amt & cond_pbr & cond_per & cond_roe & cond_op & cond_frgn & cond_nm].copy()
    
    # 3. 2차 필터링 (부채비율)
    if not df_candidates.empty:
        df_candidates = add_debt_ratio(df_candidates)
        cond_debt = df_candidates['부채비율'] <= in_max_debt
        df_final = df_candidates[cond_debt].copy().sort_values(by='시가총액', ascending=False)
        
        st.session_state['result_df'] = df_final
        st.session_state['analysis_done'] = True
    else:
        st.session_state['result_df'] = pd.DataFrame()
        st.session_state['analysis_done'] = True
        st.warning("조건을 만족하는 종목이 없습니다. 필터를 완화해보세요.")

# =========================================================
# [결과 리포트] 탭 구조로 변경
# =========================================================
if st.session_state['analysis_done'] and not st.session_state['result_df'].empty:
    df_res = st.session_state['result_df']
    
    # 상단 요약 지표 (Dashboard style)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("발굴된 종목 수", f"{len(df_res)}개")
    m2.metric("평균 PER", f"{df_res['PER'].mean():.2f}배")
    m3.metric("평균 PBR", f"{df_res['PBR'].mean():.2f}배")
    m4.metric("평균 ROE", f"{df_res['ROE'].mean():.2f}%")
    
    st.markdown("---")

    # 탭 구성
    tab1, tab2, tab3 = st.tabs(["📊 종목 리스트", "🗺️ 시장 지도 (TreeMap)", "📉 상세 차트 분석"])

    # ---------------------------------------------------------
    # TAB 1: 데이터프레임 리스트
    # ---------------------------------------------------------
    with tab1:
        st.subheader("📋 선별된 종목 목록")
        
        # 표시용 데이터 생성
        df_disp = df_res.copy()
        df_disp['시가총액'] = df_disp['시가총액'] / 100000000 
        df_disp['거래대금'] = df_disp['거래대금'] / 100000000 
        df_disp['영업이익'] = df_disp['영업이익'] / 100000000 
        df_disp = df_disp.round(2)
        
        cols_show = ['Name', '종가', '등락률', '시가총액', 'PER', 'ROE', 'PBR', '부채비율', '외국인비율']
        df_disp = df_disp[cols_show]
        df_disp.columns = ['종목명', '현재가', '등락률', '시총(억)', 'PER', 'ROE', 'PBR', '부채(%)', '외인(%)']
        
        st.dataframe(df_disp, use_container_width=True, hide_index=True)
        
        # [CSV 다운로드 버튼]
        csv = df_disp.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="💾 엑셀(CSV)로 다운로드",
            data=csv,
            file_name='저평가_우량주_리스트.csv',
            mime='text/csv',
        )

    # ---------------------------------------------------------
    # TAB 2: 트리맵 (시장 지도)
    # ---------------------------------------------------------
    with tab2:
        st.subheader("🗺️ 한눈에 보는 시장 지도")
        st.caption("박스 크기: 시가총액 / 색상: 등락률 (빨강:상승, 파랑:하락)")
        
        # 등락률 클리닝
        def clean_rate_v2(x):
            try:
                if pd.isna(x) or x == '': return 0.0
                s_val = str(x).strip().replace('%', '').replace('+', '')
                return float(s_val)
            except: return 0.0

        df_res['CleanRate'] = df_res['등락률'].apply(clean_rate_v2).fillna(0.0)
        max_val = max(abs(df_res['CleanRate'].min()), abs(df_res['CleanRate'].max()), 1.0)
        
        fig_map = px.treemap(
            df_res,
            path=[px.Constant("전체"), 'Name'],
            values='시가총액',
            color='CleanRate',
            color_continuous_scale='RdBu_r',
            range_color=[-max_val, max_val],
            custom_data=['종가', 'PER', 'PBR', 'CleanRate']
        )
        fig_map.data[0].texttemplate = "<b>%{label}</b><br>%{customdata[3]:.2f}%"
        fig_map.update_traces(hovertemplate="<b>%{label}</b><br>등락률: %{customdata[3]:.2f}%<br>PER: %{customdata[1]} / PBR: %{customdata[2]}")
        fig_map.update_layout(margin=dict(t=10, l=0, r=0, b=0), height=600)
        
        st.plotly_chart(fig_map, use_container_width=True)

    # ---------------------------------------------------------
    # TAB 3: 상세 차트
    # ---------------------------------------------------------
    with tab3:
        st.subheader("📉 종목별 상세 차트")
        col_sel, col_empty = st.columns([1, 2])
        with col_sel:
            ticker_list = [f"{row['Name']} ({ticker})" for ticker, row in df_res.iterrows()]
            selected_ticker = st.selectbox("종목을 선택하세요", ticker_list)
        
        if selected_ticker:
            code = selected_ticker.split('(')[-1].replace(')', '')
            name = selected_ticker.split(' (')[0]
            
            with st.spinner(f"'{name}' 데이터 로딩 중..."):
                df_chart = get_detailed_daily_data(code)
                
                if not df_chart.empty:
                    # 폰트 설정
                    font_path = 'NanumGothic.ttf'
                    if not os.path.exists(font_path):
                        url = 'https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf'
                        with open(font_path, 'wb') as f:
                            f.write(requests.get(url).content)
                    fm.fontManager.addfont(font_path)
                    font_prop = fm.FontProperties(fname=font_path)
                    plt.rc('font', family=font_prop.get_name())
                    plt.rcParams['axes.unicode_minus'] = False
                    
                    # 그래프 그리기
                    fig, ax = plt.subplots(figsize=(12, 6)) # 화면 비율 조정
                    ax.plot(df_chart.index, df_chart['Close'], color='black', alpha=0.6, label='주가')
                    
                    ma120 = df_chart['Close'].rolling(120).mean()
                    ma240 = df_chart['Close'].rolling(240).mean()
                    
                    ax.plot(df_chart.index, ma120, 'g--', label='120일선', linewidth=1.5)
                    ax.plot(df_chart.index, ma240, 'r--', label='240일선', linewidth=1.5)
                    
                    ax.set_title(f"{name} 주가 추이 (5년)", fontsize=15)
                    ax.legend()
                    ax.grid(True, alpha=0.3)
                    
                    st.pyplot(fig, use_container_width=True)
                    
                    # 간단 코멘트
                    curr_price = df_chart['Close'].iloc[-1]
                    ma240_val = ma240.iloc[-1]
                    
                    if curr_price < ma240_val:
                        st.success("✅ 현재 주가가 240일 장기 이동평균선 아래에 있습니다. (저점 매수 기회 가능성)")
                    else:
                        st.info("ℹ️ 현재 주가가 240일 이동평균선 위에 있습니다. (추세 상승 중)")
